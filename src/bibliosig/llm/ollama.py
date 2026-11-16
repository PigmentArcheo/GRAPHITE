"""Client minimal de l'API de génération d'Ollama."""

from __future__ import annotations

import logging
from typing import Any

import requests

from bibliosig.configuration import Configuration, adresse_ollama

journal = logging.getLogger(__name__)


class OllamaIndisponible(RuntimeError):
    """Le serveur Ollama ne répond pas."""


class ClientOllama:
    """Envoie des prompts au modèle configuré (Mistral 7B par défaut).

    Paramètres
    ----------
    configuration : Configuration
    modele : str, optionnel
        Remplace le modèle de la configuration.
    """

    def __init__(self, configuration: Configuration, modele: str | None = None) -> None:
        parametres = configuration.chaine["llm"]
        base = adresse_ollama(configuration).rstrip("/")
        self.url_generation = base + parametres["chemin_generation"]
        self.url_modeles = base + parametres["chemin_modeles"]
        self.delai_verification = parametres["delai_verification_secondes"]
        self.modele = modele or parametres["modele"]

    def verifier(self) -> None:
        """Vérifie que le serveur répond.

        Lève
        ----
        OllamaIndisponible
            Si le serveur est injoignable.
        """
        try:
            reponse = requests.get(self.url_modeles, timeout=self.delai_verification)
            reponse.raise_for_status()
        except requests.RequestException as erreur:
            raise OllamaIndisponible(
                f"Ollama injoignable ({erreur}). Lancer : ollama serve && ollama pull {self.modele}"
            ) from erreur
        journal.info("Ollama accessible, modèle %s", self.modele)

    def generer(
        self,
        prompt: str,
        delai: float,
        systeme: str | None = None,
        format_json: bool = True,
    ) -> str:
        """Renvoie le texte produit par le modèle pour un prompt.

        Paramètres
        ----------
        prompt : str
        delai : float
            Délai maximal de la requête, en secondes.
        systeme : str, optionnel
            Prompt système.
        format_json : bool
            Demande au serveur une réponse JSON.

        Renvoie
        -------
        str

        Lève
        ----
        requests.RequestException
            En cas d'échec réseau ou de réponse en erreur.
        """
        corps: dict[str, Any] = {"model": self.modele, "prompt": prompt, "stream": False}
        if systeme is not None:
            corps["system"] = systeme
        if format_json:
            corps["format"] = "json"
        reponse = requests.post(self.url_generation, json=corps, timeout=delai)
        reponse.raise_for_status()
        return reponse.json().get("response", "")
