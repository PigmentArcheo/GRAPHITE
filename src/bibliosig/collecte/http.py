"""Accès réseau commun : signature, délais, nouvelles tentatives, clés masquées."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import requests

from bibliosig import __version__
from bibliosig.configuration import Configuration

journal = logging.getLogger(__name__)

MOTIF_CLE = re.compile(r"(api_key|api-key|key|token|password)=([^&\s'\"]+)", re.IGNORECASE)
MASQUE = "***"


def masquer_secrets(texte: object) -> str:
    """Remplace la valeur des paramètres sensibles d'un texte (URL, message d'erreur).

    Paramètres
    ----------
    texte : object
        Converti en chaîne.

    Renvoie
    -------
    str
    """
    return MOTIF_CLE.sub(lambda m: f"{m.group(1)}={MASQUE}", str(texte))


def signature(configuration: Configuration) -> str:
    """User-Agent envoyé à toutes les plateformes, sans adresse électronique.

    Paramètres
    ----------
    configuration : Configuration

    Renvoie
    -------
    str
    """
    return configuration.plateformes["signature"]["modele"].format(version=__version__)


def ouvrir_session(configuration: Configuration, **entetes: str) -> requests.Session:
    """Session HTTP signée.

    Paramètres
    ----------
    configuration : Configuration
    **entetes : str
        En-têtes supplémentaires.

    Renvoie
    -------
    requests.Session
    """
    session = requests.Session()
    session.headers.update({"User-Agent": signature(configuration), **entetes})
    return session


def attendre(secondes: float) -> None:
    """Pause de politesse entre deux requêtes.

    Paramètres
    ----------
    secondes : float
    """
    if secondes > 0:
        time.sleep(secondes)


def obtenir(
    session: requests.Session,
    url: str,
    delai: float,
    params: dict[str, Any] | None = None,
) -> requests.Response:
    """Requête GET qui lève une erreur au statut HTTP d'échec, sans exposer de clé.

    Paramètres
    ----------
    session : requests.Session
    url : str
    delai : float
    params : dict, optionnel

    Renvoie
    -------
    requests.Response

    Lève
    ----
    requests.RequestException
        Message dont les clés sont masquées.
    """
    try:
        reponse = session.get(url, params=params, timeout=delai)
        reponse.raise_for_status()
    except requests.RequestException as erreur:
        raise requests.RequestException(masquer_secrets(erreur)) from None
    return reponse
