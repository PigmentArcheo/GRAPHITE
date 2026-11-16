"""Construction des expressions régulières et des textes analysés."""

from __future__ import annotations

import re
from collections.abc import Sequence

import pandas as pd

from bibliosig.communs.tableaux import texte_avec_nan


def compiler_alternatives(motifs: Sequence[str]) -> re.Pattern[str]:
    """Réunit des motifs par OU en une expression insensible à la casse.

    Paramètres
    ----------
    motifs : liste de str

    Renvoie
    -------
    re.Pattern
    """
    return re.compile("|".join(motifs), re.IGNORECASE)


def texte_analyse(notices: pd.DataFrame, champs: Sequence[str]) -> pd.Series:
    """Concatène les champs d'une notice, séparés par une espace.

    Paramètres
    ----------
    notices : pandas.DataFrame
    champs : liste de str
        Colonnes à concaténer ; une colonne absente compte comme vide.

    Renvoie
    -------
    pandas.Series
    """
    morceaux = []
    for champ in champs:
        colonne = notices[champ] if champ in notices.columns else pd.Series("", index=notices.index)
        morceaux.append(colonne.map(texte_avec_nan))
    texte = morceaux[0]
    for morceau in morceaux[1:]:
        texte = texte + " " + morceau
    return texte
