"""Outils communs des tests : configuration du dépôt, dossiers temporaires, faux réseau."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from bibliosig.configuration import Chemins, Configuration, charger_configuration

RACINE = Path(__file__).resolve().parents[1]
DONNEES_TEST = Path(__file__).resolve().parent / "donnees"


@pytest.fixture(scope="session")
def configuration() -> Configuration:
    """Configuration réelle du dépôt."""
    return charger_configuration(RACINE / "config")


@pytest.fixture
def chemins(tmp_path: Path, configuration: Configuration) -> Chemins:
    """Dossiers de données (avec les portails fabriqués) et de sorties temporaires."""
    donnees = tmp_path / "data"
    shutil.copytree(DONNEES_TEST / "portails", donnees)
    return Chemins(donnees, tmp_path / "out", configuration.chaine["fichiers"])


class FausseReponse:
    """Réponse HTTP simulée.

    Paramètres
    ----------
    contenu : bytes
    statut : int
    """

    def __init__(self, contenu: bytes, statut: int = 200) -> None:
        self.content = contenu
        self.text = contenu.decode("utf-8")
        self.status_code = statut
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        """Contenu décodé."""
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        """Lève une erreur pour un statut d'échec."""
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"statut {self.status_code}")


class FausseSession:
    """Session HTTP simulée : rejoue des réponses dans l'ordre et garde les appels.

    Paramètres
    ----------
    reponses : list of FausseReponse
    """

    def __init__(self, reponses: list[FausseReponse]) -> None:
        self.reponses = list(reponses)
        self.appels: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, params: dict[str, Any] | None = None, **options: Any) -> FausseReponse:
        """Renvoie la réponse suivante."""
        self.appels.append({"url": url, "params": params or {}, **options})
        return self.reponses.pop(0)

    def request(self, methode: str, url: str, **options: Any) -> FausseReponse:
        """Renvoie la réponse suivante (toutes méthodes)."""
        self.appels.append({"methode": methode, "url": url, **options})
        return self.reponses.pop(0)


def lire_reponse(nom: str) -> bytes:
    """Contenu d'une réponse enregistrée de ``tests/donnees/reponses``."""
    return (DONNEES_TEST / "reponses" / nom).read_bytes()
