"""Concatène les fichiers des portails sans supprimer de doublon."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from bibliosig.communs.tableaux import ecrire_bilan, ecrire_csv, lire_csv_texte
from bibliosig.configuration import Chemins, Configuration

journal = logging.getLogger(__name__)


def preparer_fichier_portail(chemin: Path, configuration: Configuration) -> pd.DataFrame:
    """Charge le fichier d'un portail et l'aligne sur le schéma commun.

    Paramètres
    ----------
    chemin : Path
        Fichier ``*_restructure.csv`` d'un portail.
    configuration : Configuration

    Renvoie
    -------
    pandas.DataFrame
        Colonnes du schéma, puis ``portails_src`` et ``source_fichier``.
    """
    colonnes = configuration.chaine["schema"]["colonnes"]
    parametres = configuration.chaine["fusion"]
    notices = lire_csv_texte(chemin)
    for colonne in colonnes:
        if colonne not in notices.columns:
            notices[colonne] = ""
    notices["source_fichier"] = chemin.name

    sans_identifiant = notices["id_biblio"].str.strip() == ""
    nombre_sans_identifiant = int(sans_identifiant.sum())
    if nombre_sans_identifiant:
        prefixe = (
            chemin.stem[: parametres["longueur_prefixe_identifiant"]].upper()
            + parametres["lettre_identifiant_forge"]
        )
        chiffres = parametres["chiffres_identifiant_forge"]
        notices.loc[sans_identifiant, "id_biblio"] = [
            f"{prefixe}{numero:0{chiffres}d}" for numero in range(1, nombre_sans_identifiant + 1)
        ]
        journal.warning("%d id_biblio forgés pour %s", nombre_sans_identifiant, chemin.name)

    notices["portails_src"] = notices["portail"].str.upper().str.strip()
    return notices[[*colonnes, "portails_src", "source_fichier"]]


def suffixer_identifiants_dupliques(notices: pd.DataFrame) -> pd.DataFrame:
    """Ajoute ``_0``, ``_1``… aux id_biblio présents dans plusieurs notices.

    Paramètres
    ----------
    notices : pandas.DataFrame

    Renvoie
    -------
    pandas.DataFrame
    """
    dupliques = notices["id_biblio"].duplicated(keep=False)
    if dupliques.any():
        journal.warning("%d id_biblio dupliqués entre portails : suffixage", int(dupliques.sum()))
        rang = notices.loc[dupliques].groupby("id_biblio").cumcount().astype(str)
        notices.loc[dupliques, "id_biblio"] = notices.loc[dupliques, "id_biblio"] + "_" + rang
    return notices


def executer(configuration: Configuration, chemins: Chemins) -> dict[str, Any]:
    """Fusionne les fichiers des portails dans ``biblio_merged.csv``.

    Paramètres
    ----------
    configuration : Configuration
    chemins : Chemins

    Renvoie
    -------
    dict
        Bilan : nombre de notices au total et par portail.

    Lève
    ----
    FileNotFoundError
        Si aucun fichier d'entrée n'est présent.
    """
    tableaux = []
    for nom_fichier in configuration.chaine["fichiers"]["entrees_fusion"]:
        chemin = chemins.donnees / nom_fichier
        if not chemin.exists():
            journal.error("Fichier introuvable, ignoré : %s", chemin)
            continue
        tableau = preparer_fichier_portail(chemin, configuration)
        journal.info("%s : %d notices", nom_fichier, len(tableau))
        tableaux.append(tableau)
    if not tableaux:
        raise FileNotFoundError(f"Aucun fichier de portail dans {chemins.donnees}")

    notices = suffixer_identifiants_dupliques(pd.concat(tableaux, ignore_index=True))
    ecrire_csv(notices, chemins.sortie("fusion"))
    bilan = {
        "notices": len(notices),
        "par_portail": {
            portail: int(nombre) for portail, nombre in notices["portail"].value_counts().items()
        },
    }
    ecrire_bilan(chemins.sortie("dossier_bilans"), "fusion", bilan)
    return bilan
