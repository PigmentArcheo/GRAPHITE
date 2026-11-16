"""Collecte Frantiq (catalogue Koha) : recherche par paire de mots, notices en MARC-XML."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError

from bibliosig.collecte.couples import paires_de_mots
from bibliosig.collecte.http import attendre, masquer_secrets, obtenir, ouvrir_session
from bibliosig.collecte.marc import (
    ENTETES_PAIRE,
    a_exclure,
    analyser_xml,
    champ_marc21,
    extraire,
    ligne_paire,
)
from bibliosig.collecte.terme_a_terme import (
    ecrire_paire,
    ecrire_recapitulatif,
    ligne_recapitulatif,
    nom_fichier_paire,
)
from bibliosig.configuration import Configuration

journal = logging.getLogger(__name__)

REGLES_MARC = {
    "titre": [("200", "a"), ("245", "a")],
    "complement_titre": [("200", "e"), ("245", "b")],
    "etiquettes_auteurs": [
        ("700", ["b", "d"]),
        ("701", ["b", "d"]),
        ("702", ["b", "d"]),
        ("100", ["b", "d"]),
        ("110", ["b", "d"]),
    ],
    "date": [("210", "d"), ("214", "d"), ("260", "c")],
    "editeur": [("210", "c"), ("214", "c"), ("260", "b")],
    "lieu": [("210", "a"), ("214", "a"), ("260", "a")],
    "isbn": [("010", "a"), ("020", "a")],
    "issn": [("011", "a"), ("022", "a")],
    "mots_cles": [("606", "a"), ("650", "a")],
    "collection": [("225", "a"), ("490", "a")],
    "revue": [("461", "t"), ("773", "t")],
    "resume": [("330", "a"), ("520", "a")],
    "type_document": [("200", "b")],
    "langue": [("101", "a"), ("041", "a")],
    "pays": [],
    "url": [("856", "u")],
    "pages": [("215", "a"), ("300", "a")],
    "note_these": [("328", "a"), ("502", "a")],
}
ENTETES = ["Biblionumber", *ENTETES_PAIRE, "Mots-cles_PACTOLS", "Resume", "Langue", "URL"]
MOTIF_NUMERO = re.compile(r"biblionumber=(\d+)")


def lire_page_resultats(html: str) -> tuple[list[str], int]:
    """Numéros de notices et nombre de résultats d'une page de recherche du catalogue.

    Paramètres
    ----------
    html : str

    Renvoie
    -------
    tuple
        (numéros dans l'ordre, sans doublon ; total annoncé).
    """
    soupe = BeautifulSoup(html, "html.parser")
    total = 0
    bloc = soupe.find("div", id="numresults")
    if bloc:
        trouve = re.search(r"(\d+)\s+r[ée]sultat", bloc.get_text())
        total = int(trouve.group(1)) if trouve else 0
    if total == 0:
        compteur = soupe.find("span", class_="nbresults")
        trouve = re.search(r"(\d+)", compteur.get_text()) if compteur else None
        total = int(trouve.group(1)) if trouve else 0
    numeros: list[str] = []
    for lien in soupe.find_all("a", href=True):
        trouve = MOTIF_NUMERO.search(lien["href"])
        if trouve and trouve.group(1) not in numeros:
            numeros.append(trouve.group(1))
    if not numeros:
        for champ_formulaire in soupe.find_all("input", {"name": "biblionumber"}):
            valeur = champ_formulaire.get("value", "")
            if valeur and valeur not in numeros:
                numeros.append(valeur)
    return numeros, total


def url_recherche(mot_a: str, mot_b: str, page: int, parametres: dict[str, Any]) -> str:
    """Adresse de la recherche avancée (mot A ET mot B, tous champs), triée par pertinence.

    Paramètres
    ----------
    mot_a, mot_b : str
    page : int
    parametres : dict

    Renvoie
    -------
    str
    """
    decalage = (page - 1) * parametres["notices_par_page"]
    return (
        f"{parametres['url']}{parametres['chemin_recherche']}?advsearch=1"
        f"&idx=kw&q={quote(mot_a)}&op=AND&idx=kw&q={quote(mot_b)}"
        f"&sort_by=relevance&offset={decalage}&count={parametres['notices_par_page']}"
    )


def notice_marc(session: requests.Session, numero: str, parametres: dict[str, Any]) -> dict[str, Any] | None:
    """Notice exportée en MARC-XML, ou ``None`` si l'export échoue.

    Paramètres
    ----------
    session : requests.Session
    numero : str
    parametres : dict

    Renvoie
    -------
    dict ou None
    """
    url = f"{parametres['url']}{parametres['chemin_export']}?op=export&bib={numero}&format=marcxml"
    try:
        racine = analyser_xml(obtenir(session, url, parametres["delai_notice_secondes"]).content)
    except requests.RequestException as erreur:
        journal.warning("Frantiq %s : %s", numero, masquer_secrets(erreur))
        return None
    except (ParseError, DefusedXmlException):
        return {"ppn": numero, "title": ""}
    notice = extraire(racine, champ_marc21, REGLES_MARC, numero)
    adresse_notice = parametres["url"] + parametres["chemin_notice"].format(numero=numero)
    notice["url"] = notice["url"] or adresse_notice
    return notice


def collecter(
    configuration: Configuration, dossier: Path, limite_couples: int | None = None
) -> dict[str, Any]:
    """Interroge Frantiq pour chaque paire de mots et écrit un fichier par paire.

    Paramètres
    ----------
    configuration : Configuration
    dossier : Path
    limite_couples : int, optionnel

    Renvoie
    -------
    dict
    """
    parametres = configuration.plateformes["frantiq"]
    communs = configuration.plateformes["mots_terme_a_terme"]
    session = ouvrir_session(configuration, **{"Accept-Language": "fr-FR,fr;q=0.9"})
    sortie = dossier / parametres["dossier"]
    recapitulatif = []
    for numero_paire, (mot_a, mot_b) in enumerate(
        paires_de_mots(configuration, "frantiq")[:limite_couples], start=1
    ):
        numeros: list[str] = []
        serveur = 0
        for page in range(1, parametres["pages_max"] + 1):
            try:
                html = obtenir(
                    session,
                    url_recherche(mot_a, mot_b, page, parametres),
                    parametres["delai_recherche_secondes"],
                ).text
            except requests.RequestException as erreur:
                journal.warning("Frantiq : %s", masquer_secrets(erreur))
                break
            trouves, total = lire_page_resultats(html)
            if page == 1:
                serveur = total
                if total == 0:
                    break
            if not trouves:
                break
            numeros.extend(trouves)
            if len(numeros) >= total:
                break
            attendre(parametres["pause_entre_pages"])
        notices = []
        for numero in numeros:
            notice = notice_marc(session, numero, parametres)
            if notice and notice.get("title"):
                notices.append(notice)
            attendre(parametres["pause_entre_notices"])
        gardees = [
            n
            for n in notices
            if not a_exclure(
                n, communs["mots_exclusion"], communs["premiere_annee"], communs["derniere_annee"]
            )
        ]
        fichier = nom_fichier_paire(mot_a, mot_b, configuration)
        recapitulatif.append(
            ligne_recapitulatif(numero_paire, mot_a, mot_b, fichier, serveur, notices, gardees)
        )
        if gardees:
            ecrire_paire(
                sortie / f"{fichier}.csv",
                ENTETES,
                [
                    [n["ppn"], *ligne_paire(n, parametres["longueur_max_resume"]), n.get("url", "")]
                    for n in gardees
                ],
            )
        attendre(parametres["pause_entre_couples"])
    sortie.mkdir(parents=True, exist_ok=True)
    ecrire_recapitulatif(sortie / "_RECAP.csv", recapitulatif)
    return {"paires": len(recapitulatif), "notices": sum(r["final"] for r in recapitulatif)}
