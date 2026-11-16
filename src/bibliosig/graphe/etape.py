"""Étape « graphe » : nœuds, relations et script ``import.cypher`` pour Neo4j.

Le graphe garde toutes les notices (une par portail) des œuvres dont au moins
une notice est classée SIG. Aucune connexion à Neo4j n'est faite : les fichiers
sont importés dans Neo4j Desktop avec ``LOAD CSV``.
"""

from __future__ import annotations

import csv
import logging
import re
import unicodedata
from collections.abc import Iterable
from importlib import resources
from pathlib import Path
from typing import Any

import pandas as pd

from bibliosig.communs.normalisation import extraire_annee
from bibliosig.communs.tableaux import (
    ecrire_bilan,
    lire_csv_texte,
    lire_json,
    texte_avec_nan,
)
from bibliosig.configuration import Chemins, Configuration

journal = logging.getLogger(__name__)

# La lettre x est acceptée comme séparateur A × B, en plus du signe ×.
MOTIF_SEPARATEUR_COUPLE = re.compile(r"\s*[×x]\s*")
MOTIF_IDENTIFIANT_SEQUENTIEL = re.compile(r"^pc_\d{6}$")


def cle_texte(texte: str, longueur: int) -> str:
    """Clé stable tirée d'un libellé : minuscules, ponctuation remplacée par ``_``.

    Paramètres
    ----------
    texte : str
    longueur : int

    Renvoie
    -------
    str
    """
    if not texte:
        return ""
    texte = texte.strip().lower()
    texte = re.sub(r"[^\w\s\-]", " ", texte)
    return re.sub(r"\s+", "_", texte).strip("_")[:longueur]


def cle_permutation_graphe(forme: str) -> str:
    """Mots triés d'une forme sans accents ni casse (règle propre à cette étape).

    Paramètres
    ----------
    forme : str

    Renvoie
    -------
    str
    """
    texte = unicodedata.normalize("NFKD", forme)
    texte = "".join(car for car in texte if not unicodedata.combining(car))
    return " ".join(sorted(re.sub(r"\s+", " ", texte).strip().lower().split()))


def decomposer_couples(champ: str, separateur: str) -> list[tuple[str, str]]:
    """Décompose ``archéologie × SIG || fouille × cartographie`` en couples (A, B).

    Paramètres
    ----------
    champ : str
    separateur : str
        Séparateur des couples (``||``).

    Renvoie
    -------
    list of tuple
    """
    couples = []
    for morceau in champ.split(separateur):
        morceau = morceau.strip()
        if not morceau:
            continue
        cotes = MOTIF_SEPARATEUR_COUPLE.split(morceau, maxsplit=1)
        if len(cotes) == 2 and cotes[0].strip() and cotes[1].strip():
            couples.append((cotes[0].strip(), cotes[1].strip()))
    return couples


def ecrire_tableau(chemin: Path, entetes: list[str], lignes: Iterable[dict[str, Any]]) -> int:
    """Écrit un fichier d'import CSV (UTF-8, guillemets au besoin).

    Paramètres
    ----------
    chemin : Path
    entetes : list of str
    lignes : itérable de dict

    Renvoie
    -------
    int
        Nombre de lignes écrites.
    """
    lignes = list(lignes)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", newline="", encoding="utf-8") as flux:
        ecrivain = csv.DictWriter(flux, fieldnames=entetes, extrasaction="ignore")
        ecrivain.writeheader()
        ecrivain.writerows(lignes)
    journal.info("%s : %d lignes", chemin.name, len(lignes))
    return len(lignes)


def lire_classification(
    chemin: Path,
) -> tuple[dict[str, dict[str, str]], set[str]]:
    """Lit les notices SIG : décision par notice et œuvres classées SIG.

    Paramètres
    ----------
    chemin : Path
        ``biblio_sig.csv``.

    Renvoie
    -------
    decisions : dict
        id_biblio vers champs ``llm_*`` (texte, « nan » si vide).
    oeuvres_sig : set of str
        Œuvres dont au moins une notice porte le label ``sig``.
    """
    decisions: dict[str, dict[str, str]] = {}
    oeuvres_sig: set[str] = set()
    for ligne in lire_csv_texte(chemin).itertuples(index=False):
        identifiant = texte_avec_nan(ligne.id_biblio).strip()
        decisions[identifiant] = {
            "llm_label": texte_avec_nan(ligne.llm_label),
            "llm_confiance": texte_avec_nan(ligne.llm_confiance),
            "llm_raison": texte_avec_nan(ligne.llm_raison),
        }
        oeuvre = texte_avec_nan(ligne.work_cluster_id)
        if oeuvre and decisions[identifiant]["llm_label"] == "sig":
            oeuvres_sig.add(oeuvre)
    return decisions, oeuvres_sig


def lire_personnes_par_forme(chemins: Chemins) -> dict[str, str]:
    """Forme de nom vers identifiant de personne, depuis ``auteurs_clusters.csv``.

    À défaut, le rattachement est reconstruit depuis ``biblio_avec_persons.csv``.

    Paramètres
    ----------
    chemins : Chemins

    Renvoie
    -------
    dict
    """
    personne_par_forme: dict[str, str] = {}
    chemin_formes = chemins.sortie("auteurs_formes")
    if chemin_formes.exists():
        formes = lire_csv_texte(chemin_formes)
        for forme, personne in zip(formes["auteur_raw"], formes["cluster_id"], strict=True):
            if forme.strip() and personne.strip():
                personne_par_forme[forme.strip()] = personne.strip()
        return personne_par_forme
    chemin_notices = chemins.sortie("auteurs_notices")
    if chemin_notices.exists():
        notices = lire_csv_texte(chemin_notices)
        for champ_auteurs, champ_personnes in zip(
            notices["auteurs"], notices["person_cluster_ids"], strict=True
        ):
            if not champ_auteurs or not champ_personnes:
                continue
            formes = [forme.strip() for forme in champ_auteurs.split("||") if forme.strip()]
            personnes = [cle.strip() for cle in champ_personnes.split("||") if cle.strip()]
            if len(formes) == len(personnes):
                for forme, personne in zip(formes, personnes, strict=True):
                    personne_par_forme.setdefault(forme, personne)
        return personne_par_forme
    journal.warning("Aucun rattachement des auteurs : chaque auteur sera une personne")
    return personne_par_forme


class RattachementPersonnes:
    """Rattache les formes de noms du graphe aux personnes, en créant les manquantes.

    Une forme inconnue prend la personne d'une permutation connue, sinon une
    nouvelle personne numérotée à la suite.

    Paramètres
    ----------
    personne_par_forme : dict
    forme_par_personne : dict
        Personne vers forme retenue (``person_clusters.json``).
    longueur_min_cle : int
    """

    def __init__(
        self,
        personne_par_forme: dict[str, str],
        forme_par_personne: dict[str, str],
        longueur_min_cle: int,
    ) -> None:
        self.personne_par_forme = personne_par_forme
        self.forme_par_personne = forme_par_personne
        self.personne_par_cle: dict[str, str] = {}
        for forme, personne in personne_par_forme.items():
            cle = cle_permutation_graphe(forme)
            if cle and len(cle) > longueur_min_cle:
                self.personne_par_cle[cle] = personne
        for personne, forme in forme_par_personne.items():
            cle = cle_permutation_graphe(str(forme))
            if cle and len(cle) > longueur_min_cle and cle not in self.personne_par_cle:
                self.personne_par_cle[cle] = personne
        numeros = [
            int(personne[3:])
            for personne in personne_par_forme.values()
            if MOTIF_IDENTIFIANT_SEQUENTIEL.match(personne)
        ]
        self.numero_suivant = max(numeros) + 1 if numeros else 0
        self.alias = 0
        self.nouvelles = 0

    def nouvelle_personne(self, forme: str) -> str:
        """Crée une personne pour une forme inconnue.

        Paramètres
        ----------
        forme : str

        Renvoie
        -------
        str
        """
        personne = f"pc_{self.numero_suivant:06d}"
        self.numero_suivant += 1
        self.personne_par_forme[forme] = personne
        self.forme_par_personne.setdefault(personne, forme)
        return personne

    def completer(self, formes: Iterable[str]) -> None:
        """Rattache toutes les formes encore inconnues.

        Paramètres
        ----------
        formes : itérable de str
        """
        for forme in formes:
            if forme in self.personne_par_forme:
                continue
            cle = cle_permutation_graphe(forme)
            if cle and cle in self.personne_par_cle:
                self.personne_par_forme[forme] = self.personne_par_cle[cle]
                self.alias += 1
            else:
                personne = self.nouvelle_personne(forme)
                if cle:
                    self.personne_par_cle[cle] = personne
                self.nouvelles += 1

    def personne(self, forme: str) -> str:
        """Personne d'une forme, créée au besoin.

        Paramètres
        ----------
        forme : str

        Renvoie
        -------
        str
        """
        if forme in self.personne_par_forme:
            return self.personne_par_forme[forme]
        cle = cle_permutation_graphe(forme)
        if cle and cle in self.personne_par_cle:
            return self.personne_par_cle[cle]
        return self.nouvelle_personne(forme)


def executer(configuration: Configuration, chemins: Chemins) -> dict[str, Any]:
    """Écrit les nœuds, les relations et ``import.cypher`` dans ``<sorties>/neo4j``.

    Paramètres
    ----------
    configuration : Configuration
    chemins : Chemins

    Renvoie
    -------
    dict
        Effectifs des nœuds et des relations.
    """
    parametres = configuration.chaine["graphe"]
    separateur_auteurs = configuration.chaine["schema"]["separateur_auteurs"]
    separateur_couples = configuration.chaine["schema"]["separateur_couples"]
    longueur_cle = parametres["longueur_cle_texte"]
    dossier = chemins.sortie("dossier_graphe")

    notices = lire_csv_texte(chemins.sortie("dedoublonnage_annotees"))
    notices_sig = lire_csv_texte(chemins.sortie("classification_gardees"))
    decisions, oeuvres_sig = lire_classification(chemins.sortie("classification_gardees"))
    if oeuvres_sig:
        notices = notices[notices["work_cluster_id"].isin(oeuvres_sig)]
    # Des notices ajoutées à la main aux notices SIG n'existent pas dans la sortie du
    # dédoublonnage : on les reprend de la classification pour qu'elles entrent au graphe.
    ajoutees = notices_sig[
        ~notices_sig["id_biblio"].str.strip().isin(notices["id_biblio"].str.strip())
        & (notices_sig["llm_label"] == "sig")
    ]
    if not ajoutees.empty:
        colonnes_communes = notices.columns.intersection(ajoutees.columns)
        notices = pd.concat([notices, ajoutees[colonnes_communes]], ignore_index=True)
        notices = notices.fillna("")
        journal.info("%d notices SIG absentes du dédoublonnage ajoutées au graphe", len(ajoutees))
    journal.info("%d notices dans %d œuvres SIG", len(notices), len(oeuvres_sig))

    chemin_oeuvres = chemins.sortie("dedoublonnage_oeuvres")
    description_oeuvres = lire_json(chemin_oeuvres) if chemin_oeuvres.exists() else {}
    chemin_personnes = chemins.sortie("auteurs_personnes")
    personnes_connues = lire_json(chemin_personnes) if chemin_personnes.exists() else {}
    forme_par_personne = {
        personne: description.get("canonical", personne)
        for personne, description in personnes_connues.items()
    }
    rattachement = RattachementPersonnes(
        lire_personnes_par_forme(chemins), forme_par_personne, parametres["longueur_min_cle_permutation"]
    )

    portails: dict[str, str] = {}
    for portail in notices["portail"]:
        libelle = portail.strip().upper()
        if portail and libelle and libelle not in portails:
            portails[libelle] = f"portal_{cle_texte(libelle, longueur_cle)}"

    notices_graphe = []
    oeuvre_par_notice: dict[str, str] = {}
    oeuvres: dict[str, str] = {}
    for ligne in notices.itertuples(index=False):
        identifiant = ligne.id_biblio.strip()
        decision = decisions.get(identifiant, {})
        notices_graphe.append(
            {
                "nodeId": f"record_{identifiant}",
                "id_biblio": identifiant,
                "id_portail": texte_avec_nan(ligne.id_portail),
                "portail": texte_avec_nan(ligne.portail).upper(),
                "titre": texte_avec_nan(ligne.titre),
                "doi": texte_avec_nan(ligne.DOI),
                "uri": texte_avec_nan(ligne.uri),
                "year": str(extraire_annee(ligne.date) or ""),
                "type": texte_avec_nan(ligne.type),
                "resume": texte_avec_nan(ligne.resume),
                "mots_cles": texte_avec_nan(ligne.mots_cles),
                "llm_label": decision.get("llm_label", ""),
                "llm_confiance": decision.get("llm_confiance", ""),
                "llm_raison": decision.get("llm_raison", ""),
            }
        )
        oeuvre = ligne.work_cluster_id.strip() if ligne.work_cluster_id else f"wc_{identifiant}"
        oeuvre_par_notice[identifiant] = oeuvre
        oeuvres.setdefault(oeuvre, texte_avec_nan(ligne.titre)[: parametres["longueur_titre_oeuvre"]])
    for oeuvre, description in description_oeuvres.items():
        if oeuvre in oeuvres and description.get("titre_repr"):
            oeuvres[oeuvre] = description["titre_repr"][: parametres["longueur_titre_oeuvre"]]

    formes_graphe = [
        forme
        for champ in notices["auteurs"]
        if champ
        for forme in (morceau.strip() for morceau in champ.split(separateur_auteurs))
        if forme
    ]
    # Ordre de première apparition des formes, pour un résultat reproductible
    # (un parcours d'ensemble Python serait dans un ordre arbitraire).
    rattachement.completer(dict.fromkeys(formes_graphe))
    journal.info("Personnes : %d alias, %d nouvelles", rattachement.alias, rattachement.nouvelles)

    auteurs: dict[str, dict[str, str]] = {}
    signatures: list[tuple[str, str, int]] = []
    personne_par_auteur: dict[str, str] = {}
    for ligne in notices.itertuples(index=False):
        identifiant = ligne.id_biblio.strip()
        if not ligne.auteurs:
            continue
        formes = [forme.strip() for forme in ligne.auteurs.split(separateur_auteurs) if forme.strip()]
        for rang, forme in enumerate(formes):
            cle_auteur = f"{identifiant}_author_{rang}"
            auteurs[cle_auteur] = {
                "display_name": forme,
                "portal": texte_avec_nan(ligne.portail).strip(),
            }
            signatures.append((identifiant, cle_auteur, rang))
            personne_par_auteur[cle_auteur] = rattachement.personne(forme)

    personnes: dict[str, str] = {}
    for cle_auteur, personne in personne_par_auteur.items():
        if personne in rattachement.forme_par_personne:
            personnes[personne] = rattachement.forme_par_personne[personne]
        else:
            personnes.setdefault(personne, auteurs[cle_auteur]["display_name"])

    concepts_a: dict[str, str] = {}
    concepts_b: dict[str, str] = {}
    couples: dict[str, str] = {}
    notice_couple: set[tuple[str, str]] = set()
    notice_concept_a: set[tuple[str, str]] = set()
    notice_concept_b: set[tuple[str, str]] = set()
    couple_concept_a: set[tuple[str, str]] = set()
    couple_concept_b: set[tuple[str, str]] = set()
    for ligne in notices.itertuples(index=False):
        identifiant = ligne.id_biblio.strip()
        for libelle_a, libelle_b in decomposer_couples(ligne.AxB, separateur_couples):
            code_a, code_b = cle_texte(libelle_a, longueur_cle), cle_texte(libelle_b, longueur_cle)
            if not code_a or not code_b:
                continue
            concepts_a[code_a] = libelle_a
            concepts_b[code_b] = libelle_b
            cle_couple = f"{code_a}__x__{code_b}"
            couples[cle_couple] = f"{libelle_a} × {libelle_b}"
            notice_couple.add((identifiant, cle_couple))
            notice_concept_a.add((identifiant, code_a))
            notice_concept_b.add((identifiant, code_b))
            couple_concept_a.add((code_a, cle_couple))
            couple_concept_b.add((code_b, cle_couple))

    effectifs = {
        "nodes_portals": ecrire_tableau(
            dossier / "nodes_portals.csv",
            ["nodeId", "label"],
            ({"nodeId": noeud, "label": libelle} for libelle, noeud in portails.items()),
        ),
        "nodes_records": ecrire_tableau(
            dossier / "nodes_records.csv",
            [
                "nodeId",
                "id_biblio",
                "id_portail",
                "portail",
                "titre",
                "doi",
                "uri",
                "year",
                "type",
                "resume",
                "mots_cles",
                "llm_label",
                "llm_confiance",
                "llm_raison",
            ],
            notices_graphe,
        ),
        "nodes_works": ecrire_tableau(
            dossier / "nodes_works.csv",
            ["nodeId", "work_key", "preferred_title"],
            (
                {"nodeId": f"work_{cle}", "work_key": cle, "preferred_title": titre}
                for cle, titre in oeuvres.items()
            ),
        ),
        "nodes_authors": ecrire_tableau(
            dossier / "nodes_authors.csv",
            ["nodeId", "author_key", "display_name", "portal"],
            ({"nodeId": cle, "author_key": cle, **valeurs} for cle, valeurs in auteurs.items()),
        ),
        "nodes_persons": ecrire_tableau(
            dossier / "nodes_persons.csv",
            ["nodeId", "person_key", "canonical_name"],
            (
                {"nodeId": f"person_{cle}", "person_key": cle, "canonical_name": nom}
                for cle, nom in personnes.items()
            ),
        ),
        "nodes_concepts_a": ecrire_tableau(
            dossier / "nodes_concepts_a.csv",
            ["nodeId", "code", "label"],
            (
                {"nodeId": f"ca_{code}", "code": code, "label": libelle}
                for code, libelle in concepts_a.items()
            ),
        ),
        "nodes_concepts_b": ecrire_tableau(
            dossier / "nodes_concepts_b.csv",
            ["nodeId", "code", "label"],
            (
                {"nodeId": f"cb_{code}", "code": code, "label": libelle}
                for code, libelle in concepts_b.items()
            ),
        ),
        "nodes_pairs": ecrire_tableau(
            dossier / "nodes_pairs.csv",
            ["nodeId", "pair_key", "label"],
            (
                {"nodeId": f"pair_{cle}", "pair_key": cle, "label": libelle}
                for cle, libelle in couples.items()
            ),
        ),
        "rels_has_record": ecrire_tableau(
            dossier / "rels_has_record.csv",
            ["portal_id", "record_id"],
            (
                {"portal_id": portails[noeud["portail"]], "record_id": noeud["id_biblio"]}
                for noeud in notices_graphe
                if noeud["portail"] in portails
            ),
        ),
        "rels_represents": ecrire_tableau(
            dossier / "rels_represents.csv",
            ["record_id", "work_key"],
            ({"record_id": notice, "work_key": oeuvre} for notice, oeuvre in oeuvre_par_notice.items()),
        ),
        "rels_authored_by": ecrire_tableau(
            dossier / "rels_authored_by.csv",
            ["record_id", "author_key", "rank"],
            ({"record_id": notice, "author_key": cle, "rank": rang} for notice, cle, rang in signatures),
        ),
        "rels_identified_as": ecrire_tableau(
            dossier / "rels_identified_as.csv",
            ["author_key", "person_key"],
            ({"author_key": cle, "person_key": personne} for cle, personne in personne_par_auteur.items()),
        ),
        "rels_matches_a": ecrire_tableau(
            dossier / "rels_matches_a.csv",
            ["record_id", "concept_code"],
            ({"record_id": notice, "concept_code": code} for notice, code in sorted(notice_concept_a)),
        ),
        "rels_matches_b": ecrire_tableau(
            dossier / "rels_matches_b.csv",
            ["record_id", "concept_code"],
            ({"record_id": notice, "concept_code": code} for notice, code in sorted(notice_concept_b)),
        ),
        "rels_matched_pair": ecrire_tableau(
            dossier / "rels_matched_pair.csv",
            ["record_id", "pair_key"],
            ({"record_id": notice, "pair_key": cle} for notice, cle in sorted(notice_couple)),
        ),
        "rels_in_pair_a": ecrire_tableau(
            dossier / "rels_in_pair_a.csv",
            ["concept_code", "pair_key"],
            ({"concept_code": code, "pair_key": cle} for code, cle in sorted(couple_concept_a)),
        ),
        "rels_in_pair_b": ecrire_tableau(
            dossier / "rels_in_pair_b.csv",
            ["concept_code", "pair_key"],
            ({"concept_code": code, "pair_key": cle} for code, cle in sorted(couple_concept_b)),
        ),
    }
    gabarit = resources.files("bibliosig.graphe").joinpath("import.cypher").read_text(encoding="utf-8")
    (dossier / "import.cypher").write_text(gabarit, encoding="utf-8")

    bilan = {
        "effectifs": effectifs,
        "noeuds": sum(n for cle, n in effectifs.items() if cle.startswith("nodes_")),
        "relations": sum(n for cle, n in effectifs.items() if cle.startswith("rels_")),
        "personnes_alias": rattachement.alias,
        "personnes_nouvelles": rattachement.nouvelles,
    }
    journal.info("Graphe : %d nœuds, %d relations", bilan["noeuds"], bilan["relations"])
    ecrire_bilan(chemins.sortie("dossier_bilans"), "graphe", bilan)
    return bilan
