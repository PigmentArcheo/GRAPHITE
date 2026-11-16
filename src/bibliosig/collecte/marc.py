"""Lecture des notices UNIMARC (SUDOC) et MARC-XML (Frantiq), avec defusedxml."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from defusedxml import ElementTree

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

ESPACE_MARC = {"marc": "http://www.loc.gov/MARC21/slim"}
MOTIF_ANNEE = re.compile(r"(19|20)\d{2}")


def analyser_xml(contenu: bytes) -> Element:
    """Analyse un document XML en refusant les constructions dangereuses.

    Paramètres
    ----------
    contenu : bytes

    Renvoie
    -------
    xml.etree.ElementTree.Element

    Lève
    ----
    xml.etree.ElementTree.ParseError
        Si le document est mal formé.
    defusedxml.DefusedXmlException
        Si le document contient une entité ou une déclaration interdite.
    """
    return ElementTree.fromstring(contenu)


def champ(notice: Element, etiquette: str, code: str | None = None) -> list[str]:
    """Valeurs d'un champ (ou d'un sous-champ) repéré par son étiquette, en parcourant tout l'arbre.

    Paramètres
    ----------
    notice : Element
    etiquette : str
    code : str, optionnel

    Renvoie
    -------
    list of str
    """
    valeurs = []
    for element in notice.iter():
        if element.attrib.get("tag", "") != etiquette:
            continue
        if code:
            valeurs.extend(
                sous.text.strip() for sous in element if sous.attrib.get("code", "") == code and sous.text
            )
        elif element.text:
            valeurs.append(element.text.strip())
    return valeurs


def champ_marc21(notice: Element, etiquette: str, code: str | None = None) -> list[str]:
    """Valeurs d'un champ MARC-XML : espace de noms MARC21, puis tout l'arbre, puis champs de contrôle.

    Paramètres
    ----------
    notice : Element
    etiquette : str
    code : str, optionnel

    Renvoie
    -------
    list of str
    """
    valeurs = []
    for zone in notice.findall(f'.//marc:datafield[@tag="{etiquette}"]', ESPACE_MARC):
        if code:
            valeurs.extend(
                sous.text.strip()
                for sous in zone.findall(f'marc:subfield[@code="{code}"]', ESPACE_MARC)
                if sous.text
            )
        elif zone.text:
            valeurs.append(zone.text.strip())
    if not valeurs:
        valeurs = champ(notice, etiquette, code)
    if not valeurs and not code:
        valeurs = [
            controle.text.strip()
            for controle in notice.findall(f'.//marc:controlfield[@tag="{etiquette}"]', ESPACE_MARC)
            if controle.text
        ]
        if not valeurs:
            valeurs = [
                element.text.strip()
                for element in notice.iter()
                if element.tag.endswith("controlfield")
                and element.attrib.get("tag", "") == etiquette
                and element.text
            ]
    return valeurs


def premiere(notice: Element, lecteur: Any, choix: Sequence[tuple[str, str]]) -> list[str]:
    """Valeurs du premier champ non vide parmi plusieurs (étiquette, code).

    Paramètres
    ----------
    notice : Element
    lecteur : callable
        ``champ`` ou ``champ_marc21``.
    choix : liste de tuple

    Renvoie
    -------
    list of str
    """
    for etiquette, code in choix:
        valeurs = lecteur(notice, etiquette, code)
        if valeurs:
            return valeurs
    return []


def extraire(
    notice: Element, lecteur: Any, regles: dict[str, list[tuple[str, str]]], identifiant: str
) -> dict[str, Any]:
    """Métadonnées d'une notice selon une table de champs (UNIMARC ou MARC21).

    Paramètres
    ----------
    notice : Element
    lecteur : callable
    regles : dict
        Nom de métadonnée → liste ordonnée de (étiquette, code).
    identifiant : str
        Identifiant de la notice (PPN ou biblionumber).

    Renvoie
    -------
    dict
    """

    def un(nom: str) -> str:
        valeurs = premiere(notice, lecteur, regles[nom])
        return valeurs[0] if valeurs else ""

    titre_propre = premiere(notice, lecteur, regles["titre"])
    complement = premiere(notice, lecteur, regles["complement_titre"])
    auteurs = []
    for etiquette in regles["etiquettes_auteurs"]:
        noms = lecteur(notice, etiquette[0], "a")
        prenoms = premiere(notice, lecteur, [(etiquette[0], code) for code in etiquette[1]])
        for rang, nom in enumerate(noms):
            prenom = prenoms[rang] if rang < len(prenoms) else ""
            auteurs.append(f"{nom}, {prenom}" if prenom else nom)
    dates = premiere(notice, lecteur, regles["date"])
    annee = MOTIF_ANNEE.search(dates[0]) if dates else None
    return {
        "ppn": identifiant,
        "title": " : ".join([*titre_propre[:1], *complement[:1]]),
        "authors": auteurs,
        "year": annee.group() if annee else "",
        "publisher": un("editeur"),
        "address": un("lieu"),
        "isbn": un("isbn"),
        "issn": un("issn"),
        "keywords": premiere(notice, lecteur, regles["mots_cles"]),
        "series": un("collection"),
        "journal": un("revue"),
        "abstract": un("resume"),
        "doctype": un("type_document"),
        "language": un("langue"),
        "country": un("pays"),
        "url": un("url"),
        "pages": un("pages"),
        "thesis_note": un("note_these"),
    }


def a_exclure(
    notice: dict[str, Any], mots_exclusion: list[str], premiere_annee: int, derniere_annee: int
) -> bool:
    """Notice hors période, ou communication, rapport, actes (titre et collection).

    Paramètres
    ----------
    notice : dict
    mots_exclusion : list of str
    premiere_annee, derniere_annee : int

    Renvoie
    -------
    bool
    """
    annee = notice.get("year", "")
    if annee.isdigit() and not premiere_annee <= int(annee) <= derniere_annee:
        return True
    texte = f"{notice.get('title', '')} {notice.get('series', '')}".lower()
    return any(mot in texte for mot in mots_exclusion)


def type_bibtex(notice: dict[str, Any]) -> str:
    """Type de document déduit des champs (thèse, mémoire, article, chapitre, livre, divers).

    Paramètres
    ----------
    notice : dict

    Renvoie
    -------
    str
    """
    titre = notice.get("title", "").lower()
    if notice.get("thesis_note", "") or "these" in titre or "thèse" in titre or "habilitation" in titre:
        return "phdthesis"
    if "memoire" in titre or "mémoire" in titre:
        return "mastersthesis"
    if notice.get("issn") or notice.get("journal"):
        return "article"
    if notice.get("isbn") and notice.get("series"):
        return "incollection"
    if notice.get("isbn"):
        return "book"
    return "misc"


ENTETES_PAIRE = ["Type", "Auteurs", "Titre", "Annee", "Revue", "Editeur", "Lieu", "Pages", "ISBN", "ISSN"]


def ligne_paire(notice: dict[str, Any], longueur_resume: int) -> list[str]:
    """Valeurs d'une notice dans le fichier par paire de mots (après l'identifiant).

    Paramètres
    ----------
    notice : dict
    longueur_resume : int

    Renvoie
    -------
    list of str
    """
    return [
        type_bibtex(notice),
        " ; ".join(notice.get("authors", [])),
        notice.get("title", ""),
        notice.get("year", ""),
        notice.get("journal", "") or notice.get("series", ""),
        notice.get("publisher", ""),
        notice.get("address", ""),
        notice.get("pages", ""),
        notice.get("isbn", ""),
        notice.get("issn", ""),
        " ; ".join(notice.get("keywords", [])),
        notice.get("abstract", "")[:longueur_resume],
        notice.get("language", ""),
    ]
