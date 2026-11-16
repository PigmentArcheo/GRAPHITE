"""Paramètres nominatifs de la figure des co-auteurs, lus hors du dépôt."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

journal = logging.getLogger(__name__)

CHEMIN_RELATIF = Path("figures") / "coauteurs.yaml"


def lire_parametres_coauteurs(dossier_donnees: Path) -> dict[str, Any]:
    """Lit ``<données>/figures/coauteurs.yaml`` : corrections de noms, positions, zooms.

    Le fichier contient des noms de personnes : il reste dans le dossier des
    données, hors Git. Un exemple fictif est fourni dans
    ``config/figures/coauteurs.exemple.yaml``.

    Paramètres
    ----------
    dossier_donnees : Path

    Renvoie
    -------
    dict
        Vide si le fichier est absent.

    Lève
    ----
    ModuleNotFoundError
        Si le fichier existe mais que PyYAML n'est pas installé.
    """
    chemin = dossier_donnees / CHEMIN_RELATIF
    if not chemin.exists():
        journal.info("Pas de paramètres nominatifs pour la figure des co-auteurs")
        return {}
    try:
        import yaml
    except ModuleNotFoundError as erreur:
        raise ModuleNotFoundError(
            "PyYAML est nécessaire pour lire figures/coauteurs.yaml : pip install bibliosig[figures]"
        ) from erreur
    with chemin.open(encoding="utf-8") as flux:
        return yaml.safe_load(flux) or {}
