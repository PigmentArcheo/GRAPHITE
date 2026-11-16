"""Lecture et écriture des tableaux CSV de la chaîne."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

journal = logging.getLogger(__name__)

VALEUR_NAN = "nan"


def lire_csv_texte(chemin: Path) -> pd.DataFrame:
    """Lit un CSV en gardant toutes les valeurs sous forme de texte.

    Paramètres
    ----------
    chemin : Path
        Fichier CSV (UTF-8, avec ou sans BOM).

    Renvoie
    -------
    pandas.DataFrame
        Tableau de chaînes ; un champ vide vaut ``""``.

    Lève
    ----
    FileNotFoundError
        Si le fichier n'existe pas.
    """
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")
    return pd.read_csv(chemin, dtype=str, keep_default_na=False)


def ecrire_csv(tableau: pd.DataFrame, chemin: Path, avec_bom: bool = True) -> None:
    """Écrit un tableau en CSV UTF-8, sans index.

    Paramètres
    ----------
    tableau : pandas.DataFrame
        Tableau à écrire.
    chemin : Path
        Fichier de sortie ; son dossier est créé au besoin.
    avec_bom : bool
        Ajoute la marque d'ordre des octets, lue par les tableurs.
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tableau.to_csv(chemin, index=False, encoding="utf-8-sig" if avec_bom else "utf-8")
    journal.info("%s : %d lignes", chemin.name, len(tableau))


def texte_avec_nan(valeur: str) -> str:
    """Rend un champ vide sous la forme du texte « nan ».

    Les champs vides sont lus comme valeurs manquantes de pandas, puis convertis
    en texte : le mot « nan » apparaît ainsi dans les prompts et dans les nœuds
    du graphe. Cette convention est conservée pour que les prompts, les motifs
    de filtrage et le graphe restent stables d'une exécution à l'autre.

    Paramètres
    ----------
    valeur : str
        Champ lu par ``lire_csv_texte``.

    Renvoie
    -------
    str
    """
    return valeur if valeur != "" else VALEUR_NAN


def ecrire_json(donnees: Any, chemin: Path) -> None:
    """Écrit des données en JSON indenté, UTF-8, caractères accentués lisibles.

    Paramètres
    ----------
    donnees : Any
        Données sérialisables.
    chemin : Path
        Fichier de sortie ; son dossier est créé au besoin.
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")


def lire_json(chemin: Path) -> Any:
    """Lit un fichier JSON.

    Paramètres
    ----------
    chemin : Path

    Renvoie
    -------
    Any

    Lève
    ----
    FileNotFoundError
        Si le fichier n'existe pas.
    """
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")
    return json.loads(chemin.read_text(encoding="utf-8"))


def ecrire_bilan(dossier_bilans: Path, etape: str, bilan: dict[str, Any]) -> None:
    """Écrit le bilan chiffré d'une étape dans ``<sorties>/bilans/<etape>.json``.

    Paramètres
    ----------
    dossier_bilans : Path
        Dossier des bilans.
    etape : str
        Nom de l'étape.
    bilan : dict
        Chiffres de l'étape.
    """
    ecrire_json(bilan, dossier_bilans / f"{etape}.json")
