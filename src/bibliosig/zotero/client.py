"""Client minimal de l'API Zotero v3 : lecture paginée, création et suppression par lots."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests

from bibliosig.collecte.http import masquer_secrets

journal = logging.getLogger(__name__)

MOTIF_IDENTIFIANT = re.compile(r"id_biblio:\s*(\S+)")
STATUTS_DEFINITIFS = (400, 403, 404, 413)


class EchecZotero(RuntimeError):
    """L'API Zotero n'a pas répondu après toutes les tentatives."""


class ClientZotero:
    """Accès à une bibliothèque Zotero ; la clé ne figure que dans l'en-tête.

    Paramètres
    ----------
    cle : str
    type_bibliotheque : {"user", "group"}
    identifiant : str
    parametres : dict
        Section ``[zotero]``.
    """

    def __init__(
        self, cle: str, type_bibliotheque: str, identifiant: str, parametres: dict[str, Any]
    ) -> None:
        self.base = f"{parametres['url']}/{type_bibliotheque}s/{identifiant}"
        self.parametres = parametres
        self.session = requests.Session()
        self.session.headers.update({"Zotero-API-Key": cle, "Zotero-API-Version": parametres["version_api"]})
        self.version: str | None = None

    def requete(self, methode: str, chemin: str, **options: Any) -> requests.Response:
        """Requête avec respect des pauses demandées par le serveur et nouvelles tentatives.

        Paramètres
        ----------
        methode, chemin : str
        **options
            Arguments de ``requests``.

        Renvoie
        -------
        requests.Response

        Lève
        ----
        requests.HTTPError
            Sur un statut définitif (400, 403, 404, 413).
        EchecZotero
            Après toutes les tentatives.
        """
        for tentative in range(self.parametres["tentatives_max"]):
            reponse = self.session.request(
                methode, self.base + chemin, timeout=self.parametres["delai_secondes"], **options
            )
            pause = reponse.headers.get("Retry-After") or reponse.headers.get("Backoff")
            if pause:
                time.sleep(int(pause))
            if "Last-Modified-Version" in reponse.headers:
                self.version = reponse.headers["Last-Modified-Version"]
            if reponse.status_code == 429:
                continue
            if reponse.status_code < 400:
                return reponse
            if reponse.status_code in STATUTS_DEFINITIFS:
                reponse.raise_for_status()
            time.sleep(self.parametres["pause_progressive_secondes"] * (tentative + 1))
        raise EchecZotero(
            masquer_secrets(f"Échec après {self.parametres['tentatives_max']} tentatives sur {chemin}")
        )

    def cles_elements(self, chemin: str = "/items/top") -> list[str]:
        """Clés de tous les éléments d'une liste (pagination).

        Paramètres
        ----------
        chemin : str

        Renvoie
        -------
        list of str
        """
        cles: list[str] = []
        while True:
            reponse = self.requete(
                "GET",
                chemin,
                params={"format": "keys", "limit": self.parametres["elements_par_page"], "start": len(cles)},
            )
            lot = [cle for cle in reponse.text.split("\n") if cle.strip()]
            if not lot:
                return cles
            cles.extend(lot)

    def identifiants_presents(self) -> dict[str, str]:
        """id_biblio déjà présents (lus dans le champ Extra) vers clé d'élément.

        Renvoie
        -------
        dict
        """
        presents: dict[str, str] = {}
        debut = 0
        while True:
            lot = self.requete(
                "GET",
                "/items/top",
                params={"format": "json", "limit": self.parametres["elements_par_page"], "start": debut},
            ).json()
            if not lot:
                return presents
            for element in lot:
                trouve = MOTIF_IDENTIFIANT.search(element["data"].get("extra", "") or "")
                if trouve:
                    presents[trouve.group(1)] = element["key"]
            debut += len(lot)

    def creer(self, elements: list[dict[str, Any]]) -> dict[str, Any]:
        """Crée un lot d'éléments.

        Paramètres
        ----------
        elements : list of dict

        Renvoie
        -------
        dict
            Réponse de l'API (``success``, ``failed``).
        """
        return self.requete(
            "POST",
            "/items",
            headers={"Content-Type": "application/json"},
            data=json.dumps(elements, ensure_ascii=False).encode("utf-8"),
        ).json()

    def supprimer(self, cles: list[str]) -> None:
        """Supprime un lot d'éléments (version de la bibliothèque exigée).

        Paramètres
        ----------
        cles : list of str
        """
        if self.version is None:
            self.requete("GET", "/items", params={"limit": 1, "format": "keys"})
        self.requete(
            "DELETE",
            "/items",
            params={"itemKey": ",".join(cles)},
            headers={"If-Unmodified-Since-Version": self.version},
        )
