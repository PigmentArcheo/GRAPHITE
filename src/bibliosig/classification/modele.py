"""Interrogation du modèle de langue pour une notice, avec point de reprise."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import requests

from bibliosig.classification.decisions import Decision, decision_depuis_reponse
from bibliosig.communs.tableaux import ecrire_json, lire_json, texte_avec_nan
from bibliosig.configuration import Configuration
from bibliosig.llm.ollama import ClientOllama

journal = logging.getLogger(__name__)


def prompt_notice(notice: pd.Series, configuration: Configuration) -> str:
    """Construit le prompt qui présente une notice au modèle.

    Paramètres
    ----------
    notice : pandas.Series
    configuration : Configuration

    Renvoie
    -------
    str
    """
    longueur_resume = configuration.chaine["classification"]["longueur_max_resume"]
    return configuration.gabarit_prompt("classification_notice").substitute(
        titre=texte_avec_nan(notice["titre"]),
        resume=texte_avec_nan(notice["resume"])[:longueur_resume],
        mots_cles=texte_avec_nan(notice["mots_cles"]),
        axb=texte_avec_nan(notice["AxB"]),
    )


def classer_par_modele(notice: pd.Series, client: ClientOllama, configuration: Configuration) -> Decision:
    """Demande au modèle si la notice traite des SIG comme outil ou méthode centrale.

    Paramètres
    ----------
    notice : pandas.Series
    client : ClientOllama
    configuration : Configuration

    Renvoie
    -------
    Decision
        Label ``erreur`` si la requête ou la réponse échoue.
    """
    systeme = (configuration.dossier / "prompts" / "classification_systeme.txt").read_text(encoding="utf-8")
    delai = configuration.chaine["classification"]["delai_llm_secondes"]
    try:
        reponse = client.generer(prompt_notice(notice, configuration), delai, systeme=systeme)
        return decision_depuis_reponse(json.loads(reponse))
    except (requests.RequestException, json.JSONDecodeError, ValueError, AttributeError) as erreur:
        return Decision("erreur", 0.0, str(erreur)[:100])


class PointDeReprise:
    """Décisions déjà obtenues, sauvegardées régulièrement dans un fichier JSON.

    Paramètres
    ----------
    chemin : Path
    frequence : int
        Nombre de nouvelles décisions entre deux sauvegardes.
    """

    def __init__(self, chemin: Path, frequence: int) -> None:
        self.chemin = chemin
        self.frequence = frequence
        self.verrou = threading.Lock()
        self.nouvelles = 0
        self.decisions: dict[str, Decision] = {}
        if chemin.exists():
            contenu = lire_json(chemin)
            self.decisions = {cle: Decision(**valeur) for cle, valeur in contenu.items()}
            journal.info("Reprise : %d notices déjà classées", len(self.decisions))

    def ajouter(self, identifiant: str, decision: Decision) -> None:
        """Enregistre une décision et sauvegarde le fichier à la fréquence prévue.

        Paramètres
        ----------
        identifiant : str
        decision : Decision
        """
        with self.verrou:
            self.decisions[identifiant] = decision
            self.nouvelles += 1
            if self.nouvelles % self.frequence == 0:
                self.sauvegarder()

    def sauvegarder(self) -> None:
        """Écrit toutes les décisions dans le fichier de reprise."""
        ecrire_json({cle: asdict(decision) for cle, decision in self.decisions.items()}, self.chemin)


def classer_notices(
    notices: Iterable[pd.Series],
    client: ClientOllama,
    reprise: PointDeReprise,
    configuration: Configuration,
) -> None:
    """Classe les notices par le modèle, en parallèle, en alimentant la reprise.

    Paramètres
    ----------
    notices : itérable de pandas.Series
    client : ClientOllama
    reprise : PointDeReprise
    configuration : Configuration
    """
    travailleurs = configuration.chaine["classification"]["travailleurs"]
    with ThreadPoolExecutor(max_workers=travailleurs) as executeur:
        taches = {
            executeur.submit(classer_par_modele, notice, client, configuration): notice["id_biblio"]
            for notice in notices
        }
        for tache in as_completed(taches):
            reprise.ajouter(taches[tache], tache.result())
    reprise.sauvegarder()
