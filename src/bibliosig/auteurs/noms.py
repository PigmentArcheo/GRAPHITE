"""Normalisation des formes de noms et clés de comparaison."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from functools import lru_cache

REMPLACEMENTS_TYPOGRAPHIQUES = {
    "‐": "-",
    "‑": "-",
    "–": "-",
    "—": "-",
    "\xa0": " ",
    " ": " ",
    " ": " ",
    "　": " ",
    "«": '"',
    "»": '"',
}


def normaliser_unicode(forme: str) -> str:
    """Réduit une forme de nom : décomposition NFKD, sans accents ni contrôles.

    Les tirets et guillemets typographiques sont unifiés, les espaces réduites.

    Paramètres
    ----------
    forme : str

    Renvoie
    -------
    str
    """
    if not forme or not forme.strip():
        return ""
    texte = unicodedata.normalize("NFKD", forme)
    texte = "".join(car for car in texte if not unicodedata.combining(car))
    for origine, remplacement in REMPLACEMENTS_TYPOGRAPHIQUES.items():
        texte = texte.replace(origine, remplacement)
    texte = "".join(car for car in texte if unicodedata.category(car)[0] != "C")
    return re.sub(r"\s+", " ", texte).strip()


@lru_cache(maxsize=None)
def normaliser_forme(forme: str) -> str:
    """Forme de nom normalisée et en minuscules, base des comparaisons.

    Paramètres
    ----------
    forme : str

    Renvoie
    -------
    str
    """
    if not forme:
        return ""
    return normaliser_unicode(forme).lower()


def cle_famille(forme_normalisee: str, particules: Iterable[str]) -> str:
    """Clé de blocage : mots du nom triés, sans initiales ni particules.

    Le tri rend la clé insensible à l'ordre prénom-nom.

    Paramètres
    ----------
    forme_normalisee : str
    particules : itérable de str

    Renvoie
    -------
    str
        Mots joints par ``|`` ; dernier mot si aucun ne reste.
    """
    if not forme_normalisee:
        return ""
    mots = re.split(r"[\s\-]+", forme_normalisee)
    exclues = set(particules)
    candidats = [mot for mot in mots if len(mot) >= 2 and mot not in exclues]
    if not candidats:
        return mots[-1] if mots else ""
    return "|".join(sorted(candidats))


def identifiant_depuis_forme(forme: str, longueur: int) -> str:
    """Identifiant provisoire de personne tiré de la forme du nom (``pc_<texte>``).

    Paramètres
    ----------
    forme : str
    longueur : int
        Nombre maximal de caractères gardés après le préfixe.

    Renvoie
    -------
    str
    """
    texte = re.sub(r"[^\w]+", "_", normaliser_forme(forme))[:longueur]
    return f"pc_{texte}"


@lru_cache(maxsize=None)
def cle_permutation(forme: str) -> str:
    """Mots de la forme normalisée, triés : même clé pour « Nom Prénom » et « Prénom Nom ».

    Paramètres
    ----------
    forme : str

    Renvoie
    -------
    str
    """
    return " ".join(sorted(normaliser_forme(forme).split()))


def richesse_unicode(forme: str) -> tuple[int, int]:
    """Nombre de lettres non ASCII, puis longueur : sert à choisir la forme la plus complète.

    Paramètres
    ----------
    forme : str

    Renvoie
    -------
    tuple of int
    """
    lettres = sum(1 for car in forme if ord(car) > 127 and unicodedata.category(car).startswith("L"))
    return lettres, len(forme)
