"""Normalisation des identifiants, titres, auteurs et dates des notices."""

from __future__ import annotations

import re
import unicodedata

MOTIF_ANNEE = re.compile(r"(1[5-9]\d{2}|20\d{2})")
MOTIF_PREFIXE_DOI = re.compile(r"^https?://(dx\.)?doi\.org/")
MOTIF_IDENTIFIANT_HAL = re.compile(r"(hal[a-z]*-\d+|halshs-\d+)")
MOTIF_IDENTIFIANT_PERSEE = re.compile(r"(persee-\d+|article\.\d+)")


def retirer_accents(texte: str) -> str:
    """Supprime les diacritiques (décomposition NFD, marques combinantes retirées).

    Paramètres
    ----------
    texte : str

    Renvoie
    -------
    str
    """
    if not texte:
        return ""
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(car for car in decompose if unicodedata.category(car) != "Mn")


def normaliser_doi(doi: str) -> str | None:
    """Met un DOI (identifiant d'objet numérique) en minuscules, sans préfixe d'URL.

    Paramètres
    ----------
    doi : str
        Champ DOI ; vide si absent.

    Renvoie
    -------
    str ou None
        ``None`` si le champ est vide.
    """
    if not doi:
        return None
    doi = doi.strip().lower()
    doi = MOTIF_PREFIXE_DOI.sub("", doi).strip("/")
    return doi or None


def normaliser_uri(uri: str) -> str | None:
    """Extrait l'identifiant HAL ou Persée d'une URI, sinon renvoie l'URI réduite.

    Paramètres
    ----------
    uri : str
        Champ uri ; vide si absent.

    Renvoie
    -------
    str ou None
    """
    if not uri:
        return None
    uri = uri.strip().lower().rstrip("/")
    for motif in (MOTIF_IDENTIFIANT_HAL, MOTIF_IDENTIFIANT_PERSEE):
        correspondance = motif.search(uri)
        if correspondance:
            return correspondance.group(1)
    return uri or None


def normaliser_titre(titre: str) -> str:
    """Réduit un titre à ses mots : minuscules, sans accents ni ponctuation.

    Seule la partie avant le premier séparateur ``|`` est gardée.

    Paramètres
    ----------
    titre : str

    Renvoie
    -------
    str
    """
    if not titre:
        return ""
    texte = titre.strip().lower()
    texte = re.split(r"\s*\|\s*", texte)[0]
    texte = retirer_accents(texte)
    texte = re.sub(r"[^\w\s]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()


def normaliser_liste_auteurs(auteurs: str, separateur: str) -> str:
    """Normalise une liste d'auteurs en minuscules sans accents, jointe par `` ; ``.

    Paramètres
    ----------
    auteurs : str
        Liste brute des auteurs.
    separateur : str
        Séparateur des auteurs dans le champ (``||``).

    Renvoie
    -------
    str
    """
    if not auteurs:
        return ""
    texte = retirer_accents(auteurs.strip().lower())
    motif = r"\s*" + re.escape(separateur) + r"\s*"
    morceaux = [morceau.strip() for morceau in re.split(motif, texte) if morceau.strip()]
    return " ; ".join(morceaux)


def extraire_annee(date: str) -> int | None:
    """Extrait la première année de quatre chiffres (1500 à 2099) d'un champ date.

    Paramètres
    ----------
    date : str

    Renvoie
    -------
    int ou None
    """
    if not date:
        return None
    correspondance = MOTIF_ANNEE.search(date)
    return int(correspondance.group(1)) if correspondance else None
