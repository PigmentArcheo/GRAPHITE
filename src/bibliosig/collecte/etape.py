"""Étape « collecte » : interroge les plateformes demandées (réseau requis)."""

from __future__ import annotations

import argparse
import logging
from typing import Any

from bibliosig.communs.tableaux import ecrire_bilan
from bibliosig.configuration import Chemins, Configuration, valeur_secrete

journal = logging.getLogger(__name__)


def executer(configuration: Configuration, chemins: Chemins, arguments: argparse.Namespace) -> dict[str, Any]:
    """Lance la collecte de chaque plateforme demandée dans ``<données>/collecte``.

    Paramètres
    ----------
    configuration : Configuration
    chemins : Chemins
    arguments : argparse.Namespace
        ``plateformes``, ``openalex_cle``, ``persee_telecharger``, ``limite_couples``.

    Renvoie
    -------
    dict
        Bilan par plateforme.
    """
    dossier = chemins.donnees / configuration.plateformes["dossiers"]["collecte"]
    limite = arguments.limite_couples
    bilan: dict[str, Any] = {}
    for plateforme in arguments.plateformes:
        journal.info("Collecte %s", plateforme)
        if plateforme == "hal":
            from bibliosig.collecte import hal

            bilan[plateforme] = hal.collecter(configuration, dossier, limite)
        elif plateforme == "openalex":
            from bibliosig.collecte import openalex

            cle = valeur_secrete(arguments.openalex_cle, "OPENALEX_API_KEY")
            bilan[plateforme] = openalex.collecter(configuration, dossier, cle, limite)
        elif plateforme == "persee":
            from bibliosig.collecte import persee

            bilan[plateforme] = persee.collecter(configuration, dossier, arguments.persee_telecharger)
        elif plateforme == "sudoc":
            from bibliosig.collecte import sudoc

            bilan[plateforme] = sudoc.collecter(configuration, dossier, limite)
        elif plateforme == "theses":
            from bibliosig.collecte import theses

            bilan[plateforme] = theses.collecter(configuration, dossier, limite)
            bilan["theses_completees"] = theses.completer_par_nnt(configuration, dossier)
        elif plateforme == "frantiq":
            from bibliosig.collecte import frantiq

            bilan[plateforme] = frantiq.collecter(configuration, dossier, limite)
    ecrire_bilan(chemins.sortie("dossier_bilans"), "collecte", bilan)
    return bilan
