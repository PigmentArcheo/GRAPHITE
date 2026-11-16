"""Étape « auteurs » : regroupe les formes de noms des notices SIG en personnes."""

from __future__ import annotations

import csv
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from bibliosig.auteurs.arbitrage import PREFIXE_FAMILLE, SourceDecisions
from bibliosig.auteurs.noms import (
    cle_famille,
    cle_permutation,
    identifiant_depuis_forme,
    normaliser_forme,
    richesse_unicode,
)
from bibliosig.auteurs.regroupements import (
    fusions_meme_oeuvre,
    regrouper_dans_famille,
    regrouper_par_coauteurs,
    regrouper_precocement,
    resoudre_reference,
    separer_auteurs,
)
from bibliosig.communs.tableaux import (
    ecrire_bilan,
    ecrire_csv,
    ecrire_json,
    lire_csv_texte,
    lire_json,
)
from bibliosig.configuration import Chemins, Configuration
from bibliosig.llm.ollama import ClientOllama
from bibliosig.normalisation.corrections import appliquer_corrections_fichier

journal = logging.getLogger(__name__)


@dataclass(frozen=True)
class Attribution:
    """Rattachement d'une forme de nom à une personne.

    Paramètres
    ----------
    cluster_id : str
        Identifiant provisoire de la personne.
    origine : str
        Règle qui a décidé le rattachement.
    canonical : str
        Forme retenue pour la personne.
    confiance : float
    """

    cluster_id: str
    origine: str
    canonical: str
    confiance: float


@dataclass
class Contexte:
    """État partagé du regroupement, dans l'ordre d'insertion.

    L'ordre des dictionnaires compte : les recherches « première forme trouvée »
    et le choix des formes retenues en dépendent.

    Paramètres
    ----------
    configuration : Configuration
    references : dict
        Forme vers liste de (id_biblio, rang).
    coauteurs : dict
        Forme vers co-auteurs normalisés.
    attributions : dict
        Forme vers Attribution.
    compteurs : Counter
    """

    configuration: Configuration
    references: dict[str, list[tuple[str, int]]]
    coauteurs: dict[str, set[str]]
    attributions: dict[str, Attribution]
    compteurs: Counter[str]

    @property
    def parametres(self) -> dict[str, Any]:
        """Section ``[auteurs]`` de la configuration."""
        return self.configuration.chaine["auteurs"]

    def confiance(self, origine: str) -> float:
        """Confiance associée à une règle de rattachement."""
        return self.parametres["confiances"][origine]

    def identifiant(self, forme: str) -> str:
        """Identifiant provisoire tiré d'une forme."""
        return identifiant_depuis_forme(forme, self.parametres["longueur_identifiant_texte"])


def extraire_formes(
    notices: pd.DataFrame, separateur: str
) -> tuple[dict[str, list[tuple[str, int]]], dict[str, set[str]]]:
    """Relève chaque forme de nom, ses notices et ses co-auteurs.

    Paramètres
    ----------
    notices : pandas.DataFrame
    separateur : str

    Renvoie
    -------
    references : dict
        Forme vers liste de (id_biblio, rang dans la notice).
    coauteurs : dict
        Forme vers ensemble des co-auteurs normalisés.
    """
    references: dict[str, list[tuple[str, int]]] = defaultdict(list)
    coauteurs: dict[str, set[str]] = defaultdict(set)
    for identifiant, champ in zip(notices["id_biblio"], notices["auteurs"], strict=True):
        formes = separer_auteurs(champ, separateur)
        for rang, forme in enumerate(formes):
            references[forme].append((identifiant, rang))
            for autre in formes:
                if autre != forme:
                    coauteurs[forme].add(normaliser_forme(autre))
    return references, coauteurs


def appliquer_annotations(contexte: Contexte, annotations: pd.DataFrame | None) -> None:
    """Rattache d'abord les formes décidées à la main (``cluster_id_final``).

    Paramètres
    ----------
    contexte : Contexte
    annotations : pandas.DataFrame ou None
        Colonnes ``auteur_raw``, ``cluster_id_final`` (ou ``cluster_id``) et,
        si présente, ``forme_retenue``.
    """
    if annotations is None:
        return
    colonne_groupe = "cluster_id_final" if "cluster_id_final" in annotations.columns else "cluster_id"
    groupe_par_forme = {}
    for forme, groupe in zip(annotations["auteur_raw"], annotations[colonne_groupe], strict=True):
        if forme.strip() and groupe.strip():
            groupe_par_forme[forme.strip()] = groupe.strip()
    journal.info("%d annotations chargées", len(groupe_par_forme))
    colonne_forme = "forme_retenue" if "forme_retenue" in annotations.columns else "auteur_raw"
    forme_retenue = dict(zip(annotations["auteur_raw"], annotations[colonne_forme], strict=True))
    for forme in contexte.references:
        if forme in groupe_par_forme:
            contexte.attributions[forme] = Attribution(
                groupe_par_forme[forme],
                "annotation",
                forme_retenue.get(forme) or forme,
                contexte.confiance("annotation"),
            )
            contexte.compteurs["annotation"] += 1


def groupes_precoces(contexte: Contexte, non_annotees: list[str]) -> dict[str, int]:
    """Regroupement précoce, puis fusion des formes isolées par co-auteurs communs.

    Paramètres
    ----------
    contexte : Contexte
    non_annotees : list of str

    Renvoie
    -------
    dict
        Forme vers numéro de groupe précoce.
    """
    parametres = contexte.parametres
    groupe_par_forme: dict[str, int] = {}
    for numero, groupe in enumerate(regrouper_precocement(non_annotees, parametres["seuil_similarite_nom"])):
        for forme in groupe:
            groupe_par_forme[forme] = numero
    journal.info("Groupes précoces : %d", len(set(groupe_par_forme.values())))

    membres_par_groupe: dict[int, list[str]] = defaultdict(list)
    for forme, numero in groupe_par_forme.items():
        membres_par_groupe[numero].append(forme)
    isolees = [membres[0] for membres in membres_par_groupe.values() if len(membres) == 1]
    groupes_coauteurs = regrouper_par_coauteurs(
        isolees,
        contexte.coauteurs,
        parametres["coauteurs_communs_min"],
        parametres["jaccard_coauteurs_min"],
        parametres["seuil_nom_coauteurs"],
    )
    numero_suivant = max(groupe_par_forme.values(), default=0) + 1
    fusions = 0
    for groupe in groupes_coauteurs:
        if len(groupe) == 1:
            continue
        fusions += 1
        for forme in groupe:
            groupe_par_forme[forme] = numero_suivant
        numero_suivant += 1
    journal.info("Fusions par co-auteurs : %d groupes", fusions)
    return groupe_par_forme


def familles_a_trancher(
    contexte: Contexte, non_annotees: list[str], groupe_par_forme: dict[str, int]
) -> dict[str, list[str]]:
    """Range les formes par famille de noms ; les groupes précoces seuls sont rattachés.

    Paramètres
    ----------
    contexte : Contexte
    non_annotees : list of str
    groupe_par_forme : dict

    Renvoie
    -------
    dict
        Famille vers formes restant à départager.
    """
    particules = contexte.parametres["particules"]
    groupes_par_famille: dict[str, list[tuple[int | None, str]]] = defaultdict(list)
    for forme in non_annotees:
        famille = cle_famille(normaliser_forme(forme), particules)
        if famille:
            groupes_par_famille[famille].append((groupe_par_forme.get(forme), forme))
        else:
            contexte.attributions[forme] = Attribution(
                contexte.identifiant(forme), "singleton", forme, contexte.confiance("singleton")
            )
            contexte.compteurs["singleton_vide"] += 1

    identifiant_par_groupe: dict[int | None, str] = {}
    formes_par_famille: dict[str, list[str]] = defaultdict(list)
    for famille, couples in groupes_par_famille.items():
        formes_par_groupe: dict[int | None, list[str]] = defaultdict(list)
        for numero, forme in couples:
            formes_par_groupe[numero].append(forme)
        for numero, formes in formes_par_groupe.items():
            if len(formes) == 1:
                identifiant = identifiant_par_groupe.setdefault(numero, f"pc_precoce_{numero:06d}")
                contexte.attributions[formes[0]] = Attribution(
                    identifiant, "fuzzy_precoce", formes[0], contexte.confiance("fuzzy_precoce")
                )
                contexte.compteurs["fuzzy_precoce"] += 1
            else:
                formes_par_famille[famille].extend(formes)
    return formes_par_famille


def rattacher_groupes(contexte: Contexte, groupes: list[list[str]], origine: str, cle_confiance: str) -> None:
    """Rattache chaque groupe à sa forme la plus longue.

    Paramètres
    ----------
    contexte : Contexte
    groupes : list of list of str
    origine : str
    cle_confiance : str
    """
    for groupe in groupes:
        retenue = max(groupe, key=len)
        identifiant = contexte.identifiant(retenue)
        for forme in groupe:
            contexte.attributions[forme] = Attribution(
                identifiant, origine, retenue, contexte.confiance(cle_confiance)
            )
            contexte.compteurs[origine] += 1


def appliquer_decision_modele(contexte: Contexte, groupes_modele: list[Any]) -> None:
    """Rattache les formes selon les groupes proposés par le modèle.

    Paramètres
    ----------
    contexte : Contexte
    groupes_modele : list
        Éléments ``{"canonical": ..., "members": [...]}``.

    Lève
    ----
    AttributeError, TypeError
        Si la réponse n'a pas la forme attendue ; les rattachements déjà faits
        restent acquis.
    """
    for groupe in groupes_modele:
        retenue = groupe.get("canonical", "")
        membres = groupe.get("members", [])
        identifiant = contexte.identifiant(retenue)
        origine = "llm_fusion" if len(membres) > 1 else "llm_singleton"
        for forme in membres:
            if forme in contexte.references or forme in contexte.attributions:
                contexte.attributions[forme] = Attribution(
                    identifiant, origine, retenue, contexte.confiance("llm")
                )
                contexte.compteurs[origine] += 1


def trancher_familles(
    contexte: Contexte,
    formes_par_famille: dict[str, list[str]],
    source: SourceDecisions | None,
    limite_familles: int | None,
) -> dict[str, Any]:
    """Départage chaque famille : regroupement approché, puis modèle si plusieurs groupes.

    Paramètres
    ----------
    contexte : Contexte
    formes_par_famille : dict
    source : SourceDecisions ou None
        ``None`` pour se passer du modèle.
    limite_familles : int, optionnel
        Nombre maximal de familles soumises au modèle (essai).

    Renvoie
    -------
    dict
        Décisions du modèle, à écrire dans le point de reprise.
    """
    parametres = contexte.parametres
    groupes_par_famille: dict[str, list[list[str]]] = {}
    for famille, formes in formes_par_famille.items():
        if len(formes) == 1:
            contexte.attributions[formes[0]] = Attribution(
                contexte.identifiant(formes[0]),
                "famille_unique",
                formes[0],
                contexte.confiance("famille_unique"),
            )
            contexte.compteurs["famille_unique"] += 1
            continue
        groupes_par_famille[famille] = regrouper_dans_famille(formes, parametres["seuil_similarite_nom"])

    a_soumettre = []
    for famille, groupes in groupes_par_famille.items():
        if not groupes:
            continue
        if len(groupes) == 1:
            retenue = max(groupes[0], key=len)
            identifiant = contexte.identifiant(retenue)
            for forme in groupes[0]:
                contexte.attributions[forme] = Attribution(
                    identifiant, "fuzzy", retenue, contexte.confiance("fuzzy")
                )
                contexte.compteurs["fuzzy_fusion" if len(groupes[0]) > 1 else "fuzzy_singleton"] += 1
        elif source is None or sum(len(groupe) for groupe in groupes) < parametres["taille_min_groupe_llm"]:
            rattacher_groupes(contexte, groupes, "fuzzy_no_llm", "fuzzy_no_llm")
        else:
            a_soumettre.append((famille, groupes))
    journal.info("Familles à soumettre au modèle : %d", len(a_soumettre))
    if limite_familles is not None:
        a_soumettre = a_soumettre[:limite_familles]

    decisions: dict[str, Any] = {}
    if source is None:
        return decisions
    for famille, groupes in a_soumettre:
        formes = [forme for groupe in groupes for forme in groupe]
        try:
            reponse = source.decision(famille, formes)
        except requests.RequestException:
            continue
        if reponse:
            groupes_modele = reponse.get("clusters", [])
            decisions[PREFIXE_FAMILLE + famille] = groupes_modele
            try:
                appliquer_decision_modele(contexte, groupes_modele)
            except (AttributeError, TypeError) as erreur:
                journal.error("Réponse du modèle mal formée pour %s : %s", famille, erreur)
        else:
            for groupe in groupes:
                retenue = max(groupe, key=len)
                identifiant = contexte.identifiant(retenue)
                for forme in groupe:
                    if forme not in contexte.attributions:
                        contexte.attributions[forme] = Attribution(
                            identifiant, "fuzzy_no_llm", retenue, contexte.confiance("fuzzy_no_llm")
                        )
                        contexte.compteurs["fuzzy_no_llm"] += 1
    return decisions


def appliquer_fusions_meme_oeuvre(contexte: Contexte, fusions: dict[str, str]) -> None:
    """Rattache chaque forme absorbée à la personne de sa forme de référence.

    Paramètres
    ----------
    contexte : Contexte
    fusions : dict
        Forme absorbée vers forme retenue.
    """
    for forme in fusions:
        reference = resoudre_reference(forme, fusions)
        attribution_reference = contexte.attributions.get(reference)
        if attribution_reference is not None:
            identifiant = attribution_reference.cluster_id
        else:
            reference_normalisee = normaliser_forme(reference)
            identifiant = next(
                (
                    attribution.cluster_id
                    for attribution in contexte.attributions.values()
                    if normaliser_forme(attribution.canonical) == reference_normalisee
                ),
                None,
            ) or contexte.identifiant(reference)
        contexte.attributions[forme] = Attribution(
            identifiant, "meme_work", reference, contexte.confiance("meme_work")
        )
    if fusions:
        contexte.compteurs["meme_work"] = len(fusions)


def construire_personnes(
    contexte: Contexte,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Regroupe les attributions par personne et numérote les personnes.

    Paramètres
    ----------
    contexte : Contexte

    Renvoie
    -------
    personnes : dict
        Identifiant définitif (``pc_000000``…) vers forme retenue, membres et
        nombre de références.
    renumerotation : dict
        Identifiant provisoire vers identifiant définitif.
    """
    provisoires: dict[str, dict[str, Any]] = {}
    for forme, attribution in contexte.attributions.items():
        personne = provisoires.get(attribution.cluster_id)
        if personne is None:
            personne = {"canonical": attribution.canonical, "members": [], "nb_works": 0}
            provisoires[attribution.cluster_id] = personne
        elif richesse_unicode(attribution.canonical) > richesse_unicode(personne["canonical"]):
            personne["canonical"] = attribution.canonical
        personne["members"].append(forme)
        personne["nb_works"] += len(contexte.references.get(forme, []))
    personnes = {}
    renumerotation = {}
    for numero, (provisoire, personne) in enumerate(sorted(provisoires.items())):
        definitif = f"pc_{numero:06d}"
        personnes[definitif] = personne
        renumerotation[provisoire] = definitif
    return personnes, renumerotation


def reintegrer_formes_manquantes(contexte: Contexte, groupe_par_forme: dict[str, int]) -> int:
    """Rattache les formes encore sans personne : alias d'un groupe, permutation, ou seule.

    Paramètres
    ----------
    contexte : Contexte
    groupe_par_forme : dict
        Groupes précoces.

    Renvoie
    -------
    int
        Nombre de formes réintégrées.
    """
    longueur_min = contexte.parametres["longueur_min_cle_permutation"]
    plafond = contexte.confiance("alias_max")
    attribuees_par_groupe: dict[int, list[str]] = defaultdict(list)
    for forme, numero in groupe_par_forme.items():
        if forme in contexte.attributions:
            attribuees_par_groupe[numero].append(forme)

    reintegrees = 0
    for forme in contexte.references:
        if forme in contexte.attributions:
            continue
        reintegrees += 1
        numero = groupe_par_forme.get(forme)
        if numero is not None and attribuees_par_groupe.get(numero):
            modele = contexte.attributions[attribuees_par_groupe[numero][0]]
            contexte.attributions[forme] = replace(
                modele, origine=modele.origine + "+alias", confiance=min(modele.confiance, plafond)
            )
            continue
        cle = cle_permutation(forme)
        if cle and len(cle) > longueur_min:
            for autre, attribution in contexte.attributions.items():
                if cle_permutation(autre) == cle:
                    contexte.attributions[forme] = replace(
                        attribution,
                        origine=attribution.origine + "+alias_perm",
                        confiance=min(attribution.confiance, plafond),
                    )
                    break
        if forme not in contexte.attributions:
            contexte.attributions[forme] = Attribution(
                contexte.identifiant(forme),
                "fallback_singleton",
                forme,
                contexte.confiance("fallback_singleton"),
            )
    return reintegrees


def ecrire_formes(contexte: Contexte, renumerotation: dict[str, str], chemin: Path) -> None:
    """Écrit ``auteurs_clusters.csv`` : une ligne par forme, triée.

    Paramètres
    ----------
    contexte : Contexte
    renumerotation : dict
    chemin : Path
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", newline="", encoding="utf-8") as flux:
        ecrivain = csv.DictWriter(
            flux, fieldnames=["auteur_raw", "cluster_id", "origine", "canonical", "confiance"]
        )
        ecrivain.writeheader()
        for forme, attribution in sorted(contexte.attributions.items()):
            ecrivain.writerow(
                {
                    "auteur_raw": forme,
                    "cluster_id": renumerotation.get(attribution.cluster_id, attribution.cluster_id),
                    "origine": attribution.origine,
                    "canonical": attribution.canonical,
                    "confiance": f"{attribution.confiance:.2f}",
                }
            )


def identifiants_personnes(
    champ: str, contexte: Contexte, renumerotation: dict[str, str], separateur: str
) -> str:
    """Identifiants des personnes d'un champ auteurs, dans l'ordre des auteurs.

    Paramètres
    ----------
    champ : str
    contexte : Contexte
    renumerotation : dict
    separateur : str

    Renvoie
    -------
    str
    """
    identifiants = []
    for forme in separer_auteurs(champ, separateur):
        attribution = contexte.attributions.get(forme)
        provisoire = attribution.cluster_id if attribution else ""
        identifiants.append(renumerotation.get(provisoire, provisoire))
    return separateur.join(identifiants)


def executer(
    configuration: Configuration,
    chemins: Chemins,
    annotations: Path | None = None,
    rejouer: bool = False,
    dossier_decisions: Path | None = None,
    sans_llm: bool = False,
    limite_familles: int | None = None,
) -> dict[str, Any]:
    """Regroupe les formes de noms des notices SIG en personnes.

    Paramètres
    ----------
    configuration : Configuration
    chemins : Chemins
    annotations : Path, optionnel
        Décisions manuelles ; par défaut ``<données>/auteurs_clusters_corriges.csv``
        s'il existe.
    rejouer : bool
        Relit les décisions du modèle dans le point de reprise existant.
    dossier_decisions : Path, optionnel
        Dossier du point de reprise à rejouer.
    sans_llm : bool
        Se passe du modèle.
    limite_familles : int, optionnel
        Nombre maximal de familles soumises au modèle (essai).

    Renvoie
    -------
    dict
        Bilan : formes, personnes, origines des rattachements.
    """
    separateur = configuration.chaine["schema"]["separateur_auteurs"]
    parametres = configuration.chaine["auteurs"]
    notices = lire_csv_texte(chemins.sortie("classification_gardees"))
    references, coauteurs = extraire_formes(notices, separateur)
    contexte = Contexte(configuration, references, coauteurs, {}, Counter())
    journal.info("%d formes de noms distinctes", len(references))

    chemin_toutes = chemins.sortie("dedoublonnage_annotees")
    toutes = lire_csv_texte(chemin_toutes) if chemin_toutes.exists() else notices
    fusions = fusions_meme_oeuvre(toutes, parametres["seuil_similarite_nom"], separateur)
    journal.info("%d formes rapprochées dans une même œuvre", len(fusions))

    chemin_annotations = annotations or chemins.entree("decisions_auteurs")
    appliquer_annotations(
        contexte, lire_csv_texte(chemin_annotations) if chemin_annotations.exists() else None
    )

    non_annotees = [forme for forme in references if forme not in contexte.attributions]
    groupe_par_forme = groupes_precoces(contexte, non_annotees)
    formes_par_famille = familles_a_trancher(contexte, non_annotees, groupe_par_forme)

    source: SourceDecisions | None = None
    reprise = chemins.sortie("auteurs_reprise")
    if rejouer:
        noms = Chemins(
            dossier_decisions or chemins.sorties, dossier_decisions or chemins.sorties, chemins.noms
        )
        source = SourceDecisions(
            configuration, decisions_enregistrees=lire_json(noms.sortie("auteurs_reprise"))
        )
    elif not sans_llm:
        client = ClientOllama(configuration)
        client.verifier()
        source = SourceDecisions(configuration, client=client)
    decisions = trancher_familles(contexte, formes_par_famille, source, limite_familles)
    if source is not None and not rejouer:
        ecrire_json(decisions, reprise)

    appliquer_fusions_meme_oeuvre(contexte, fusions)
    personnes, renumerotation = construire_personnes(contexte)
    ecrire_json(personnes, chemins.sortie("auteurs_personnes"))
    reintegrees = reintegrer_formes_manquantes(contexte, groupe_par_forme)
    ecrire_formes(contexte, renumerotation, chemins.sortie("auteurs_formes"))

    avec_personnes = notices.copy()
    avec_personnes["person_cluster_ids"] = avec_personnes["auteurs"].map(
        lambda champ: identifiants_personnes(champ, contexte, renumerotation, separateur)
    )
    ecrire_csv(avec_personnes, chemins.sortie("auteurs_notices"), avec_bom=False)
    for cle in ("auteurs_formes", "auteurs_notices"):
        appliquer_corrections_fichier(chemins.sortie(cle), configuration, chemins)

    bilan = {
        "formes_dans_notices": len(references),
        "formes_rattachees": len(contexte.attributions),
        "personnes": len(personnes),
        "groupes_distincts": len(
            {renumerotation.get(a.cluster_id, a.cluster_id) for a in contexte.attributions.values()}
        ),
        "fusions_meme_oeuvre": len(fusions),
        "formes_reintegrees": reintegrees,
        "decisions_modele": len(decisions),
        "origines": dict(Counter(a.origine for a in contexte.attributions.values())),
    }
    ecrire_bilan(chemins.sortie("dossier_bilans"), "auteurs", bilan)
    return bilan
