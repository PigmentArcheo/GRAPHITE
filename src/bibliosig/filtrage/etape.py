"""Passe négative (hors sujet évident) et passe positive (vocabulaire archéologique)."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from bibliosig.communs.tableaux import ecrire_bilan, ecrire_csv, lire_csv_texte
from bibliosig.configuration import Chemins, Configuration
from bibliosig.filtrage.motifs import compiler_alternatives, texte_analyse
from bibliosig.normalisation.corrections import appliquer_corrections_fichier

journal = logging.getLogger(__name__)


def masque_rejet_negatif(notices: pd.DataFrame, configuration: Configuration) -> pd.Series:
    """Marque les notices hors sujet sans aucun signal archéologique.

    Paramètres
    ----------
    notices : pandas.DataFrame
    configuration : Configuration

    Renvoie
    -------
    pandas.Series
        Vrai pour une notice à rejeter.
    """
    parametres = configuration.filtres["filtre_negatif"]
    texte = texte_analyse(notices, parametres["champs_texte"])
    hors_sujet = texte.str.contains(compiler_alternatives(parametres["motifs_hors_sujet"]))
    signal = texte.str.contains(compiler_alternatives(parametres["signaux_archeologiques"]))
    return hors_sujet & ~signal


def masque_conservation_positive(notices: pd.DataFrame, configuration: Configuration) -> pd.Series:
    """Marque les notices au vocabulaire archéologique ou au concept A strict.

    Le second critère rattrape les notices sans résumé, dont le couple de concepts
    suffit à montrer le sujet archéologique.

    Paramètres
    ----------
    notices : pandas.DataFrame
    configuration : Configuration

    Renvoie
    -------
    pandas.Series
        Vrai pour une notice à garder.
    """
    parametres = configuration.filtres["filtre_positif"]
    texte = texte_analyse(notices, parametres["champs_texte"])
    vocabulaire = texte.str.contains(compiler_alternatives(parametres["motifs_archeologiques"]))
    couples = notices["AxB"] if "AxB" in notices.columns else pd.Series("", index=notices.index)
    concept_strict = couples.str.contains(compiler_alternatives(parametres["concepts_a_stricts"]))
    return vocabulaire | concept_strict


def repartition_par_portail(notices: pd.DataFrame) -> dict[str, int]:
    """Compte les notices par portail, du plus fréquent au moins fréquent.

    Paramètres
    ----------
    notices : pandas.DataFrame

    Renvoie
    -------
    dict
    """
    comptes = notices.groupby("portail").size().sort_values(ascending=False)
    return {portail: int(nombre) for portail, nombre in comptes.items()}


def filtrer(
    configuration: Configuration,
    chemins: Chemins,
    passe: str,
) -> dict[str, Any]:
    """Applique une passe de filtre et écrit les notices gardées et rejetées.

    Paramètres
    ----------
    configuration : Configuration
    chemins : Chemins
    passe : {"negatif", "positif"}

    Renvoie
    -------
    dict
        Bilan : notices en entrée, gardées, rejetées, rejets par portail.

    Lève
    ----
    ValueError
        Si la passe est inconnue.
    """
    if passe == "negatif":
        notices = lire_csv_texte(chemins.sortie("fusion"))
        gardees_masque = ~masque_rejet_negatif(notices, configuration)
        cle_gardees, cle_rejetees = "filtre_negatif_gardees", "filtre_negatif_rejetees"
    elif passe == "positif":
        notices = lire_csv_texte(chemins.sortie("filtre_negatif_gardees"))
        gardees_masque = masque_conservation_positive(notices, configuration)
        cle_gardees, cle_rejetees = "filtre_positif_gardees", "filtre_positif_rejetees"
    else:
        raise ValueError(f"Passe de filtre inconnue : {passe}")

    gardees = notices[gardees_masque]
    rejetees = notices[~gardees_masque]
    ecrire_csv(gardees, chemins.sortie(cle_gardees))
    ecrire_csv(rejetees, chemins.sortie(cle_rejetees))
    bilan = {
        "entree": len(notices),
        "gardees": len(gardees),
        "rejetees": len(rejetees),
        "rejets_par_portail": repartition_par_portail(rejetees),
    }
    for cle in (cle_gardees, cle_rejetees):
        corrige = appliquer_corrections_fichier(chemins.sortie(cle), configuration, chemins)
        bilan[f"apres_corrections_{cle}"] = len(corrige)
    journal.info("Filtre %s : %d gardées, %d rejetées", passe, len(gardees), len(rejetees))
    ecrire_bilan(chemins.sortie("dossier_bilans"), f"filtre_{passe}", bilan)
    return bilan


def executer(configuration: Configuration, chemins: Chemins) -> dict[str, Any]:
    """Enchaîne la passe négative puis la passe positive.

    Paramètres
    ----------
    configuration : Configuration
    chemins : Chemins

    Renvoie
    -------
    dict
        Bilans des deux passes.
    """
    return {
        "negatif": filtrer(configuration, chemins, "negatif"),
        "positif": filtrer(configuration, chemins, "positif"),
    }
