"""Collecte SUDOC par le service SRU : une requête par paire de mots (19 × 14)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import requests
from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError

from bibliosig.collecte.couples import paires_de_mots
from bibliosig.collecte.http import attendre, masquer_secrets, obtenir, ouvrir_session
from bibliosig.collecte.marc import ENTETES_PAIRE, a_exclure, analyser_xml, champ, extraire, ligne_paire
from bibliosig.collecte.terme_a_terme import (
    ecrire_paire,
    ecrire_recapitulatif,
    ligne_recapitulatif,
    nom_fichier_paire,
)
from bibliosig.configuration import Configuration

journal = logging.getLogger(__name__)

ESPACE_SRU = "{http://www.loc.gov/zing/srw/}"
REGLES_UNIMARC = {
    "titre": [("200", "a")],
    "complement_titre": [("200", "e")],
    "etiquettes_auteurs": [("700", ["b"]), ("701", ["b"]), ("702", ["b"])],
    "date": [("210", "d"), ("214", "d")],
    "editeur": [("210", "c"), ("214", "c")],
    "lieu": [("210", "a"), ("214", "a")],
    "isbn": [("010", "a")],
    "issn": [("011", "a")],
    "mots_cles": [("606", "a")],
    "collection": [("225", "a")],
    "revue": [("461", "t")],
    "resume": [("330", "a")],
    "type_document": [("200", "b")],
    "langue": [("101", "a")],
    "pays": [("102", "a")],
    "url": [("856", "u")],
    "pages": [("215", "a")],
    "note_these": [("328", "a")],
}
ENTETES = ["PPN", *ENTETES_PAIRE, "Mots-cles", "Resume", "Langue", "Pays", "URL"]


def coder_terme(terme: str) -> str:
    """Terme pour la requête SRU : une expression est mise entre guillemets codés.

    Paramètres
    ----------
    terme : str

    Renvoie
    -------
    str
    """
    return "%22" + terme.replace(" ", "%20") + "%22" if " " in terme else terme


def requete(mot_a: str, mot_b: str) -> str:
    """Requête SRU : les deux mots dans tous les champs, en français ou publié en France.

    Paramètres
    ----------
    mot_a, mot_b : str

    Renvoie
    -------
    str
    """
    return f"tou%3D{coder_terme(mot_a)} and tou%3D{coder_terme(mot_b)} and (lan%3Dfre or pay%3Dfr)"


def url_page(requete_sru: str, debut: int, parametres: dict[str, Any]) -> str:
    """Adresse d'une page de résultats (la requête est déjà codée).

    Paramètres
    ----------
    requete_sru : str
    debut : int
    parametres : dict

    Renvoie
    -------
    str
    """
    return (
        f"{parametres['url']}?operation=searchRetrieve&version=1.1&recordSchema=unimarc"
        f"&maximumRecords={parametres['notices_par_page']}&startRecord={debut}&query={requete_sru}"
    )


def notice_unimarc(enregistrement: Any, parametres: dict[str, Any]) -> dict[str, Any]:
    """Métadonnées d'un enregistrement UNIMARC.

    Paramètres
    ----------
    enregistrement : Element
    parametres : dict

    Renvoie
    -------
    dict
    """
    identifiants = champ(enregistrement, "001")
    ppn = identifiants[0] if identifiants else ""
    notice = extraire(enregistrement, champ, REGLES_UNIMARC, ppn)
    notice["url"] = notice["url"] or parametres["url_notice"].format(ppn=ppn)
    return notice


def interroger(
    session: requests.Session, mot_a: str, mot_b: str, parametres: dict[str, Any]
) -> tuple[list[dict[str, Any]], int]:
    """Toutes les pages d'une paire ; une erreur réseau ou XML arrête la paire.

    Paramètres
    ----------
    session : requests.Session
    mot_a, mot_b : str
    parametres : dict

    Renvoie
    -------
    tuple
        Notices avec un titre, nombre annoncé par le serveur.
    """
    notices: list[dict[str, Any]] = []
    debut, total = 1, None
    while True:
        try:
            contenu = obtenir(
                session, url_page(requete(mot_a, mot_b), debut, parametres), parametres["delai_secondes"]
            ).content
            racine = analyser_xml(contenu)
        except requests.RequestException as erreur:
            journal.error("SUDOC : %s", masquer_secrets(erreur))
            break
        except (ParseError, DefusedXmlException) as erreur:
            journal.error("SUDOC : réponse XML refusée (%s)", erreur)
            break
        if total is None:
            element = racine.find(f".//{ESPACE_SRU}numberOfRecords")
            total = int(element.text) if element is not None and element.text else 0
            if total == 0:
                break
        enregistrements = racine.findall(f".//{ESPACE_SRU}recordData")
        if not enregistrements:
            break
        notices.extend(n for n in (notice_unimarc(e, parametres) for e in enregistrements) if n.get("title"))
        debut += parametres["notices_par_page"]
        if debut > total:
            break
        attendre(parametres["pause_entre_pages"])
    return notices, total or 0


def collecter(
    configuration: Configuration, dossier: Path, limite_couples: int | None = None
) -> dict[str, Any]:
    """Interroge SUDOC pour chaque paire de mots et écrit un fichier par paire.

    Paramètres
    ----------
    configuration : Configuration
    dossier : Path
    limite_couples : int, optionnel

    Renvoie
    -------
    dict
    """
    parametres = configuration.plateformes["sudoc"]
    communs = configuration.plateformes["mots_terme_a_terme"]
    session = ouvrir_session(configuration)
    sortie = dossier / parametres["dossier"]
    recapitulatif = []
    for numero, (mot_a, mot_b) in enumerate(paires_de_mots(configuration, "sudoc")[:limite_couples], start=1):
        notices, serveur = interroger(session, mot_a, mot_b, parametres)
        gardees = [
            n
            for n in notices
            if not a_exclure(
                n, communs["mots_exclusion"], communs["premiere_annee"], communs["derniere_annee"]
            )
        ]
        fichier = nom_fichier_paire(mot_a, mot_b, configuration)
        recapitulatif.append(ligne_recapitulatif(numero, mot_a, mot_b, fichier, serveur, notices, gardees))
        if gardees:
            ecrire_paire(
                sortie / f"{fichier}.csv",
                ENTETES,
                [
                    [
                        n["ppn"],
                        *ligne_paire(n, parametres["longueur_max_resume"]),
                        n.get("country", ""),
                        n.get("url", ""),
                    ]
                    for n in gardees
                ],
            )
        journal.info("[%d] %s × %s : %d gardées", numero, mot_a, mot_b, len(gardees))
        attendre(parametres["pause_entre_couples"])
    sortie.mkdir(parents=True, exist_ok=True)
    ecrire_recapitulatif(sortie / "_RECAP.csv", recapitulatif)
    return {"paires": len(recapitulatif), "notices": sum(r["final"] for r in recapitulatif)}
