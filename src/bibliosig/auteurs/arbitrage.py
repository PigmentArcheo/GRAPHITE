"""Arbitrage par le modèle de langue des familles de noms ambiguës."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from bibliosig.auteurs.noms import normaliser_forme
from bibliosig.configuration import Configuration
from bibliosig.llm.ollama import ClientOllama

journal = logging.getLogger(__name__)

PREFIXE_FAMILLE = "fam:"


def prompt_famille(formes: list[str], configuration: Configuration) -> str:
    """Construit le prompt qui présente une famille de formes au modèle.

    Paramètres
    ----------
    formes : list of str
    configuration : Configuration

    Renvoie
    -------
    str
    """
    return configuration.gabarit_prompt("auteurs_groupe").substitute(
        groupe_brut=json.dumps(formes, ensure_ascii=False),
        groupe_normalise=json.dumps([normaliser_forme(forme) for forme in formes], ensure_ascii=False),
    )


def lire_reponse(texte: str) -> dict[str, Any] | None:
    """Extrait l'objet JSON d'une réponse libre du modèle.

    Trois tentatives : le plus grand bloc entre accolades, un bloc de code
    Markdown, puis la seule liste ``"clusters"``.

    Paramètres
    ----------
    texte : str

    Renvoie
    -------
    dict ou None
        ``None`` (ou un dict vide) si rien n'est lisible.
    """
    resultat = None
    bloc = re.search(r"\{.*\}", texte, re.DOTALL)
    if bloc:
        try:
            resultat = json.loads(bloc.group())
        except json.JSONDecodeError:
            resultat = None
    if not resultat:
        bloc = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texte, re.DOTALL)
        if bloc:
            try:
                resultat = json.loads(bloc.group(1))
            except json.JSONDecodeError:
                resultat = None
    if not resultat:
        bloc = re.search(r'"clusters"\s*:\s*(\[.*?\])', texte, re.DOTALL)
        if bloc:
            try:
                resultat = {"clusters": json.loads(bloc.group(1))}
            except json.JSONDecodeError:
                resultat = None
    return resultat


def interroger_modele(
    formes: list[str], client: ClientOllama, configuration: Configuration
) -> dict[str, Any] | None:
    """Demande au modèle quelles formes d'une famille désignent la même personne.

    Paramètres
    ----------
    formes : list of str
    client : ClientOllama
    configuration : Configuration

    Renvoie
    -------
    dict ou None
        Réponse lue, ou ``None`` si elle est illisible.

    Lève
    ----
    requests.RequestException
        En cas d'échec réseau.
    """
    delai = configuration.chaine["auteurs"]["delai_llm_secondes"]
    texte = client.generer(prompt_famille(formes, configuration), delai, format_json=False)
    return lire_reponse(texte)


class SourceDecisions:
    """Fournit la décision du modèle pour une famille : en direct ou rejouée.

    Paramètres
    ----------
    configuration : Configuration
    client : ClientOllama, optionnel
        Client pour les appels en direct.
    decisions_enregistrees : dict, optionnel
        Contenu d'un point de reprise (``fam:<clé>`` vers liste de groupes),
        pour le rejeu.
    """

    def __init__(
        self,
        configuration: Configuration,
        client: ClientOllama | None = None,
        decisions_enregistrees: dict[str, Any] | None = None,
    ) -> None:
        self.configuration = configuration
        self.client = client
        self.enregistrees = decisions_enregistrees
        self.nouvelles: dict[str, Any] = {}

    def decision(self, famille: str, formes: list[str]) -> dict[str, Any] | None:
        """Renvoie la réponse lue pour une famille, ou ``None`` si elle est illisible.

        En rejeu, une famille absente du point de reprise est traitée comme une
        réponse illisible.

        Paramètres
        ----------
        famille : str
        formes : list of str

        Renvoie
        -------
        dict ou None

        Lève
        ----
        requests.RequestException
            En cas d'échec réseau en direct.
        """
        cle = PREFIXE_FAMILLE + famille
        if self.enregistrees is not None:
            if cle in self.enregistrees:
                return {"clusters": self.enregistrees[cle]}
            return None
        if self.client is None:
            raise RuntimeError("Aucun client Ollama pour l'arbitrage en direct")
        try:
            return interroger_modele(formes, self.client, self.configuration)
        except requests.RequestException:
            journal.exception("Échec de l'appel au modèle pour la famille %s", famille)
            raise
