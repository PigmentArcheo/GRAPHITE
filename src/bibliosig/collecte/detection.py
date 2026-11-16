"""Relevé des termes d'un concept effectivement présents dans une notice."""

from __future__ import annotations

import re
from collections.abc import Iterable


def termes_trouves(texte: str, termes: Iterable[str]) -> str:
    """Termes présents dans le texte (mots entiers, sans tenir compte de la casse).

    Paramètres
    ----------
    texte : str
    termes : itérable de str

    Renvoie
    -------
    str
        Termes trouvés, joints par `` | ``.
    """
    minuscules = texte.lower()
    trouves = [terme for terme in termes if re.search(r"\b" + re.escape(terme.lower()) + r"\b", minuscules)]
    return " | ".join(trouves)
