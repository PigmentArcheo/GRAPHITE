"""Collecte HAL : une requête par couple de concepts, chaque concept réuni par OU."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

import requests

from bibliosig.collecte.couples import Concept, couples_de_concepts
from bibliosig.collecte.detection import termes_trouves
from bibliosig.collecte.http import attendre, masquer_secrets, obtenir, ouvrir_session
from bibliosig.collecte.registre import RegistreNotices
from bibliosig.configuration import Configuration

journal = logging.getLogger(__name__)


def clause_concept(concept: Concept, champs: list[str]) -> str:
    """Clause Solr : chaque terme cherché dans chaque champ, le tout réuni par OU.

    L'API de HAL refuse une requête par terme à l'échelle de la matrice : un
    concept entier tient donc dans une seule clause.

    Paramètres
    ----------
    concept : Concept
    champs : list of str

    Renvoie
    -------
    str
    """
    par_terme = [
        "(" + " OR ".join(f'{champ}:"{terme}"' for champ in champs) + ")" for terme in concept.termes
    ]
    return "(" + " OR ".join(par_terme) + ")"


def requete_couple(concept_a: Concept, concept_b: Concept, parametres: dict[str, Any]) -> str:
    """Requête d'un couple : clause A ET clause B.

    Paramètres
    ----------
    concept_a, concept_b : Concept
    parametres : dict
        Section ``[hal]``.

    Renvoie
    -------
    str
    """
    champs = parametres["champs_recherche"]
    return f"{clause_concept(concept_a, champs)} AND {clause_concept(concept_b, champs)}"


def aplatir(document: dict[str, Any], champs: list[str]) -> dict[str, Any]:
    """Document HAL → dict à plat ; les listes sont jointes par `` | ``.

    Paramètres
    ----------
    document : dict
    champs : list of str

    Renvoie
    -------
    dict
    """
    plat = {}
    for champ in champs:
        valeur = document.get(champ, "")
        plat[champ] = " | ".join(str(v) for v in valeur) if isinstance(valeur, list) else valeur
    return plat


def interroger(
    session: requests.Session, requete: str, parametres: dict[str, Any]
) -> tuple[int, list[dict[str, Any]]]:
    """Toutes les pages de résultats d'une requête.

    Paramètres
    ----------
    session : requests.Session
    requete : str
    parametres : dict

    Renvoie
    -------
    tuple
        Nombre de résultats annoncé, documents.
    """
    taille = parametres["notices_par_page"]
    filtre_types = "docType_s:(" + " OR ".join(parametres["types_documents"]) + ")"
    documents: list[dict[str, Any]] = []
    debut = 0
    total = None
    while total is None or debut < total:
        if debut:
            attendre(parametres["pause_entre_pages"])
        reponse = obtenir(
            session,
            parametres["url"],
            parametres["delai_secondes"],
            params={
                "q": requete,
                "wt": "json",
                "rows": taille,
                "start": debut,
                "fl": ",".join(parametres["champs_renvoyes"]),
                "sort": parametres["tri"],
                "fq": filtre_types,
            },
        ).json()
        total = reponse["response"]["numFound"]
        documents.extend(reponse["response"]["docs"])
        debut += taille
    return total, documents


def collecter(
    configuration: Configuration, dossier: Path, limite_couples: int | None = None
) -> dict[str, Any]:
    """Interroge HAL pour chaque couple A × B et écrit les trois fichiers de collecte.

    Paramètres
    ----------
    configuration : Configuration
    dossier : Path
    limite_couples : int, optionnel

    Renvoie
    -------
    dict
        Lignes écrites, notices uniques, couples traités.
    """
    parametres = configuration.plateformes["hal"]
    champs = parametres["champs_renvoyes"]
    session = ouvrir_session(configuration)
    registre = RegistreNotices(parametres["champ_identifiant"])
    couples = couples_de_concepts(configuration, "hal")[:limite_couples]
    statistiques = []
    lignes = 0
    dossier.mkdir(parents=True, exist_ok=True)
    entetes = ["groupe_A", "termes_A_matchés", "groupe_B", "termes_B_matchés", "query_rank", *champs]
    with (dossier / parametres["fichier_resultats"]).open("w", newline="", encoding="utf-8-sig") as flux:
        ecrivain = csv.DictWriter(flux, fieldnames=entetes, extrasaction="ignore")
        ecrivain.writeheader()
        for rang_couple, (concept_a, concept_b) in enumerate(couples, start=1):
            journal.info("[%d/%d] %s × %s", rang_couple, len(couples), concept_a.libelle, concept_b.libelle)
            try:
                total, documents = interroger(
                    session, requete_couple(concept_a, concept_b, parametres), parametres
                )
            except (requests.RequestException, KeyError, ValueError) as erreur:
                message = masquer_secrets(erreur)
                journal.error("Échec du couple : %s", message)
                statistiques.append(
                    {
                        "groupe_A": concept_a.libelle,
                        "groupe_B": concept_b.libelle,
                        "num_found": f"ERREUR: {message}",
                    }
                )
                attendre(parametres["pause_entre_couples"])
                continue
            statistiques.append(
                {"groupe_A": concept_a.libelle, "groupe_B": concept_b.libelle, "num_found": total}
            )
            for rang, document in enumerate(documents, start=1):
                texte = " ".join(
                    " ".join(map(str, v)) if isinstance(v, list) else str(v)
                    for v in (document.get(c, "") for c in parametres["champs_detection"])
                )
                plat = aplatir(document, champs)
                ecrivain.writerow(
                    {
                        "groupe_A": concept_a.libelle,
                        "termes_A_matchés": termes_trouves(texte, concept_a.termes),
                        "groupe_B": concept_b.libelle,
                        "termes_B_matchés": termes_trouves(texte, concept_b.termes),
                        "query_rank": rang,
                        **plat,
                    }
                )
                lignes += 1
                if plat.get(parametres["champ_identifiant"]):
                    registre.enregistrer(
                        plat[parametres["champ_identifiant"]], plat, concept_a.libelle, concept_b.libelle
                    )
            attendre(parametres["pause_entre_couples"])
    uniques = registre.ecrire(dossier / parametres["fichier_dedoublonne"], champs)
    ecrire_statistiques(dossier / parametres["fichier_statistiques"], statistiques)
    return {"lignes": lignes, "notices_uniques": uniques, "couples": len(couples)}


def ecrire_statistiques(chemin: Path, statistiques: list[dict[str, Any]]) -> None:
    """Écrit le nombre de résultats par couple.

    Paramètres
    ----------
    chemin : Path
    statistiques : list of dict
    """
    with chemin.open("w", newline="", encoding="utf-8-sig") as flux:
        ecrivain = csv.DictWriter(flux, fieldnames=["groupe_A", "groupe_B", "num_found"])
        ecrivain.writeheader()
        ecrivain.writerows(statistiques)
