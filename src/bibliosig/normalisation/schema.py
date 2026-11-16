"""Nettoyage des champs des collectes avant le passage au schéma commun."""

from __future__ import annotations

import re
import unicodedata

MOTIF_ANNEE_ISOLEE = re.compile(r"\b(\d{4})\b")


def joindre_auteurs_barre(champ: str) -> str:
    """Auteurs séparés par ``|`` (ou par une virgule suivie d'une majuscule) → ``a || b``.

    Paramètres
    ----------
    champ : str

    Renvoie
    -------
    str
    """
    if not champ:
        return ""
    morceaux = re.split(r"\s*\|\s*|\s*,\s*(?=[A-ZÀÂÉÈÊËÎÏÔÙÛÜÇ])", champ)
    return " || ".join(morceau.strip() for morceau in morceaux if morceau.strip())


def joindre_auteurs_barre_simple(champ: str) -> str:
    """Auteurs séparés par ``|`` → ``a || b``.

    Paramètres
    ----------
    champ : str

    Renvoie
    -------
    str
    """
    if not champ:
        return ""
    morceaux = re.split(r"\s*\|\s*", champ)
    return " || ".join(morceau.strip() for morceau in morceaux if morceau.strip())


def premier_resume(champ: str) -> str:
    """Premier segment d'un résumé multilingue séparé par `` | ``.

    Paramètres
    ----------
    champ : str

    Renvoie
    -------
    str
    """
    return champ.split(" | ")[0].strip() if champ else ""


def annee(champ: str) -> str:
    """Année isolée de quatre chiffres, sinon le champ tel quel.

    Paramètres
    ----------
    champ : str

    Renvoie
    -------
    str
    """
    if not champ:
        return ""
    texte = str(champ).strip()
    correspondance = MOTIF_ANNEE_ISOLEE.search(texte)
    return correspondance.group(1) if correspondance else texte


def mots_cles_hal(champ: str) -> str:
    """Mots-clés HAL séparés par ``|`` ou ``;`` → ``a | b``.

    Paramètres
    ----------
    champ : str

    Renvoie
    -------
    str
    """
    if not champ:
        return ""
    morceaux = re.split(r"\s*\|\s*|\s*;\s*", champ)
    return " | ".join(morceau.strip() for morceau in morceaux if morceau.strip())


def mots_cles_barre(champ: str) -> str:
    """Mots-clés séparés par ``|`` → ``a | b``.

    Paramètres
    ----------
    champ : str

    Renvoie
    -------
    str
    """
    if not champ:
        return ""
    morceaux = re.split(r"\s*\|\s*", champ)
    return " | ".join(morceau.strip() for morceau in morceaux if morceau.strip())


def auteurs_nom_prenom(champ: str, separateur: str) -> str:
    """Auteurs « Nom, Prénom » séparés par ``separateur`` → ``Nom Prénom || …``.

    Paramètres
    ----------
    champ : str
    separateur : str

    Renvoie
    -------
    str
    """
    if not champ:
        return ""
    auteurs = []
    for auteur in champ.split(separateur):
        auteur = re.sub(r"\s*,\s*", " ", auteur.strip()).strip()
        if auteur:
            auteurs.append(auteur)
    return " || ".join(auteurs)


def etiquette_theses(texte: str) -> str:
    """Étiquette de fichier de theses.fr : sans accents, minuscules, ``_`` pour les espaces.

    Paramètres
    ----------
    texte : str

    Renvoie
    -------
    str
    """
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[-\s]+", "_", re.sub(r"[^\w\s-]", "", texte.lower())).strip("_")
