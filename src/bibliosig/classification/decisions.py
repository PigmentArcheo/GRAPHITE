"""Décisions de classification : forme commune, pré-filtre et relecture des sorties."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from bibliosig.communs.tableaux import texte_avec_nan
from bibliosig.configuration import Configuration


@dataclass(frozen=True)
class Decision:
    """Classement d'une notice.

    Paramètres
    ----------
    label : str
        ``sig``, ``hors_sig`` ou ``erreur``.
    confiance : float
        Entre 0 et 1.
    raison : str
    """

    label: str
    confiance: float
    raison: str


def decision_depuis_reponse(reponse: dict[str, Any]) -> Decision:
    """Lit la réponse JSON du modèle (clés courtes ``l``, ``c``, ``r`` ou longues).

    Paramètres
    ----------
    reponse : dict

    Renvoie
    -------
    Decision
    """
    return Decision(
        label=reponse.get("l", reponse.get("label", "erreur")),
        confiance=float(reponse.get("c", reponse.get("confiance", 0.0)) or 0.0),
        raison=reponse.get("r", reponse.get("raison", "")),
    )


def motif_prefiltre(configuration: Configuration) -> re.Pattern[str]:
    """Expression du pré-filtre SIG (logiciels, sigles, géoréférencement, géomatique).

    Paramètres
    ----------
    configuration : Configuration

    Renvoie
    -------
    re.Pattern
    """
    parametres = configuration.filtres["prefiltre_sig"]
    logiciels = r"\b(?:" + "|".join(parametres["logiciels"]) + r")\b"
    return re.compile("|".join([logiciels, *parametres["autres_motifs"]]), re.IGNORECASE)


def prefiltrer(notice: pd.Series, motif: re.Pattern[str], configuration: Configuration) -> Decision | None:
    """Classe d'office comme SIG une notice au vocabulaire SIG évident.

    Le pré-filtre évite que le modèle rejette des cas évidents.

    Paramètres
    ----------
    notice : pandas.Series
    motif : re.Pattern
    configuration : Configuration

    Renvoie
    -------
    Decision ou None
        ``None`` si le modèle doit trancher.
    """
    parametres = configuration.filtres["prefiltre_sig"]
    texte = " ".join(texte_avec_nan(notice.get(champ, "")) for champ in parametres["champs_texte"])
    if motif.search(texte):
        return Decision(parametres["label"], parametres["confiance"], parametres["raison"])
    return None
