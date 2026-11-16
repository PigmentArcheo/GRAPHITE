"""Lecture de la configuration, des chemins et des variables d'environnement."""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

journal = logging.getLogger(__name__)

FICHIERS_CONFIGURATION = ("chaine", "filtres", "concepts", "plateformes", "analyses")


@dataclass(frozen=True)
class Configuration:
    """Paramètres du projet, lus dans les fichiers TOML du dossier ``config/``.

    Paramètres
    ----------
    dossier : Path
        Dossier de configuration.
    chaine, filtres, concepts, plateformes, analyses : dict
        Contenu de chaque fichier TOML du même nom.
    """

    dossier: Path
    chaine: dict[str, Any]
    filtres: dict[str, Any]
    concepts: dict[str, Any]
    plateformes: dict[str, Any]
    analyses: dict[str, Any]

    def gabarit_prompt(self, nom: str) -> Template:
        """Renvoie le gabarit d'un prompt de ``config/prompts/``.

        Paramètres
        ----------
        nom : str
            Nom du fichier, sans l'extension ``.txt``.

        Renvoie
        -------
        Template
            Gabarit à compléter avec ``substitute``.
        """
        chemin = self.dossier / "prompts" / f"{nom}.txt"
        return Template(chemin.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Chemins:
    """Dossiers des données d'entrée et des sorties.

    Paramètres
    ----------
    donnees : Path
        Dossier des données fournies par l'utilisateur (hors Git).
    sorties : Path
        Dossier des sorties de la chaîne (hors Git).
    noms : dict
        Noms de fichiers de la section ``[fichiers]`` de ``chaine.toml``.
    """

    donnees: Path
    sorties: Path
    noms: dict[str, Any]

    def entree(self, cle: str) -> Path:
        """Renvoie le chemin d'un fichier du dossier des données.

        Paramètres
        ----------
        cle : str
            Clé de la section ``[fichiers]``.

        Renvoie
        -------
        Path
        """
        return self.donnees / self.noms[cle]

    def sortie(self, cle: str) -> Path:
        """Renvoie le chemin d'un fichier du dossier des sorties.

        Paramètres
        ----------
        cle : str
            Clé de la section ``[fichiers]``.

        Renvoie
        -------
        Path
        """
        return self.sorties / self.noms[cle]


def charger_configuration(dossier: Path) -> Configuration:
    """Lit tous les fichiers TOML de configuration.

    Paramètres
    ----------
    dossier : Path
        Dossier contenant ``chaine.toml``, ``filtres.toml``, etc.

    Renvoie
    -------
    Configuration

    Lève
    ----
    FileNotFoundError
        Si un fichier de configuration manque.
    """
    contenus: dict[str, dict[str, Any]] = {}
    for nom in FICHIERS_CONFIGURATION:
        chemin = dossier / f"{nom}.toml"
        if not chemin.exists():
            raise FileNotFoundError(f"Fichier de configuration introuvable : {chemin}")
        with chemin.open("rb") as flux:
            contenus[nom] = tomllib.load(flux)
    return Configuration(dossier=dossier, **contenus)


def charger_fichier_env(chemin: Path) -> None:
    """Charge un fichier ``.env`` sans écraser les variables déjà définies.

    Paramètres
    ----------
    chemin : Path
        Fichier de lignes ``NOM=valeur`` ; les lignes vides et ``#`` sont ignorées.
    """
    if not chemin.exists():
        return
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        nom, valeur = ligne.split("=", 1)
        valeur = valeur.strip().strip('"').strip("'")
        if valeur:
            os.environ.setdefault(nom.strip(), valeur)


def valeur_secrete(argument: str | None, variable: str) -> str | None:
    """Renvoie un secret : l'argument prend le pas sur la variable d'environnement.

    Paramètres
    ----------
    argument : str ou None
        Valeur passée en ligne de commande.
    variable : str
        Nom de la variable d'environnement.

    Renvoie
    -------
    str ou None
    """
    if argument:
        return argument
    return os.environ.get(variable) or None


def adresse_ollama(configuration: Configuration) -> str:
    """Renvoie l'adresse du serveur Ollama (``OLLAMA_URL`` ou configuration)."""
    return os.environ.get("OLLAMA_URL") or configuration.chaine["llm"]["url"]


def adresse_neo4j(configuration: Configuration) -> str:
    """Renvoie l'adresse de Neo4j (``NEO4J_URI`` ou configuration)."""
    return os.environ.get("NEO4J_URI") or configuration.chaine["neo4j"]["uri"]
