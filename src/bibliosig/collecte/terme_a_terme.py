"""Écriture commune des portails interrogés terme à terme : un fichier par paire de mots."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from bibliosig.collecte.marc import type_bibtex
from bibliosig.configuration import Configuration

CHAMPS_RECAPITULATIF = [
    "num",
    "mot_A",
    "mot_B",
    "fichier",
    "serveur",
    "extraits",
    "exclus",
    "final",
    "articles",
    "chapitres",
    "theses",
    "livres",
    "autres",
]


def nom_fichier_paire(mot_a: str, mot_b: str, configuration: Configuration) -> str:
    """Nom du fichier d'une paire (SUDOC, Frantiq), sans extension.

    Paramètres
    ----------
    mot_a, mot_b : str
    configuration : Configuration

    Renvoie
    -------
    str
    """
    mots = configuration.plateformes["mots_terme_a_terme"]
    etiquettes = mots["etiquettes_fichiers"]
    separateur = configuration.plateformes["normalisation"]["terme_a_terme"]["separateur_paire_fichier"]
    return (
        etiquettes.get(mot_a, mot_a.replace(" ", "_"))
        + separateur
        + etiquettes.get(mot_b, mot_b.replace(" ", "_"))
    )


def ligne_recapitulatif(
    numero: int,
    mot_a: str,
    mot_b: str,
    fichier: str,
    serveur: int,
    notices: list[dict[str, Any]],
    gardees: list[dict[str, Any]],
) -> dict[str, Any]:
    """Ligne du récapitulatif d'une paire : effectifs et types de documents.

    Paramètres
    ----------
    numero : int
    mot_a, mot_b, fichier : str
    serveur : int
        Nombre de résultats annoncé par la plateforme.
    notices, gardees : list of dict
        Notices extraites, puis gardées après exclusion.

    Renvoie
    -------
    dict
    """
    types = [type_bibtex(notice) for notice in gardees]
    return {
        "num": numero,
        "mot_A": mot_a,
        "mot_B": mot_b,
        "fichier": fichier,
        "serveur": serveur,
        "extraits": len(notices),
        "exclus": len(notices) - len(gardees),
        "final": len(gardees),
        "articles": types.count("article"),
        "chapitres": types.count("incollection"),
        "theses": types.count("phdthesis") + types.count("mastersthesis"),
        "livres": types.count("book"),
        "autres": types.count("misc"),
    }


def ecrire_paire(chemin: Path, entetes: list[str], lignes: list[list[str]]) -> None:
    """Écrit le fichier d'une paire : séparateur point-virgule, valeurs entre guillemets.

    Paramètres
    ----------
    chemin : Path
    entetes : list of str
    lignes : list of list of str
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", encoding="utf-8-sig", newline="") as flux:
        ecrivain = csv.writer(flux, delimiter=";", quoting=csv.QUOTE_ALL)
        ecrivain.writerow(entetes)
        ecrivain.writerows(lignes)


def ecrire_recapitulatif(chemin: Path, lignes: list[dict[str, Any]]) -> None:
    """Écrit ``_RECAP.csv`` : une ligne par paire de mots.

    Paramètres
    ----------
    chemin : Path
    lignes : list of dict
    """
    with chemin.open("w", encoding="utf-8-sig", newline="") as flux:
        ecrivain = csv.DictWriter(flux, fieldnames=CHAMPS_RECAPITULATIF, delimiter=";", quoting=csv.QUOTE_ALL)
        ecrivain.writeheader()
        ecrivain.writerows(lignes)
