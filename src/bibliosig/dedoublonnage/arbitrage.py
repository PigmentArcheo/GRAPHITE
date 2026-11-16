"""Troisième passe : avis du modèle de langue sur les paires de score intermédiaire."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from bibliosig.configuration import Configuration
from bibliosig.dedoublonnage.notices import NoticeComparee
from bibliosig.llm.ollama import ClientOllama

journal = logging.getLogger(__name__)


def valeur_prompt(valeur: object) -> str:
    """Rend une valeur pour le prompt (vide → « nan »).

    Paramètres
    ----------
    valeur : object
        Champ texte, ou année entière ou absente.

    Renvoie
    -------
    str
    """
    if valeur is None or valeur == "":
        return "nan"
    if isinstance(valeur, int):
        # L'année était stockée dans une colonne flottante de pandas.
        return f"{float(valeur)}"
    return str(valeur)


def prompt_paire(premiere: NoticeComparee, seconde: NoticeComparee, configuration: Configuration) -> str:
    """Construit le prompt qui présente deux notices au modèle.

    Paramètres
    ----------
    premiere, seconde : NoticeComparee
    configuration : Configuration

    Renvoie
    -------
    str
    """
    gabarit = configuration.gabarit_prompt("dedoublonnage_paire")
    champs = {}
    for suffixe, notice in (("a", premiere), ("b", seconde)):
        champs[f"titre_{suffixe}"] = valeur_prompt(notice.titre)
        champs[f"auteurs_{suffixe}"] = valeur_prompt(notice.auteurs)
        champs[f"annee_{suffixe}"] = valeur_prompt(notice.annee)
        champs[f"doi_{suffixe}"] = valeur_prompt(notice.doi)
    return gabarit.substitute(champs)


def arbitrer_paires(
    notices: dict[str, NoticeComparee],
    journal_paires: list[dict[str, Any]],
    configuration: Configuration,
    client: ClientOllama,
    seuil_confiance: float,
) -> list[dict[str, Any]]:
    """Demande au modèle si les paires de score intermédiaire sont des doublons.

    Cet avis est seulement consigné : une fusion déjà faite n'est pas défaite,
    et les œuvres ne changent pas.

    Paramètres
    ----------
    notices : dict
    journal_paires : list of dict
        Journal de la passe de similarité.
    configuration : Configuration
    client : ClientOllama
    seuil_confiance : float
        Confiance à partir de laquelle un refus est noté « rejeté ».

    Renvoie
    -------
    list of dict
        Une entrée par paire arbitrée, avec verdict, confiance et raison.
    """
    parametres = configuration.chaine["dedoublonnage"]
    systeme = (configuration.dossier / "prompts" / "dedoublonnage_systeme.txt").read_text(encoding="utf-8")
    intermediaires = [
        entree
        for entree in journal_paires
        if parametres["borne_basse_arbitrage"] <= entree["score"] < parametres["borne_haute_arbitrage"]
    ]
    journal.info("%d paires soumises au modèle", len(intermediaires))
    avis: list[dict[str, Any]] = []
    for entree in intermediaires:
        prompt = prompt_paire(notices[entree["id1"]], notices[entree["id2"]], configuration)
        try:
            reponse = json.loads(client.generer(prompt, parametres["delai_llm_secondes"], systeme=systeme))
        except (requests.RequestException, json.JSONDecodeError, KeyError) as erreur:
            reponse = {"est_doublon": False, "confiance": 0.0, "raison": f"erreur: {erreur}"}
        confiance = float(reponse.get("confiance", 0))
        refus = not bool(reponse.get("est_doublon", False)) and confiance >= seuil_confiance
        avis.append(
            {
                **entree,
                "llm_verdict": "rejeté" if refus else "confirmé",
                "llm_conf": confiance,
                "raison": reponse.get("raison", ""),
            }
        )
    return avis
