"""Étape « zotero » : envoi des notices, sans doublon, ou purge de la bibliothèque."""

from __future__ import annotations

import argparse
import json
import logging
import time
from typing import Any

import requests

from bibliosig.communs.tableaux import lire_csv_texte
from bibliosig.configuration import Chemins, Configuration, valeur_secrete
from bibliosig.zotero.client import ClientZotero
from bibliosig.zotero.notices import element_zotero

journal = logging.getLogger(__name__)


class ConfirmationManquante(RuntimeError):
    """La purge n'a pas été confirmée explicitement."""


def notices_a_envoyer(
    notices: list[dict[str, str]], par_oeuvre: bool, filtre_sig: bool
) -> list[dict[str, str]]:
    """Notices retenues : SIG seulement si demandé, une par œuvre si demandé, jamais deux id_biblio égaux.

    Paramètres
    ----------
    notices : list of dict
    par_oeuvre, filtre_sig : bool

    Renvoie
    -------
    list of dict
    """
    if filtre_sig:
        notices = [n for n in notices if (n.get("llm_label") or "").strip() == "sig"]
    if par_oeuvre:
        vues: set[str] = set()
        uniques = []
        for notice in notices:
            oeuvre = notice.get("work_cluster_id") or notice.get("id_biblio")
            if oeuvre not in vues:
                vues.add(oeuvre)
                uniques.append(notice)
        notices = uniques
    identifiants: set[str] = set()
    retenues = []
    for notice in notices:
        identifiant = notice.get("id_biblio")
        if identifiant and identifiant not in identifiants:
            identifiants.add(identifiant)
            retenues.append(notice)
    return retenues


def purger(client: ClientZotero | None, parametres: dict[str, Any], confirmation: str, essai: bool) -> int:
    """Vide la bibliothèque et sa corbeille ; irréversible.

    Paramètres
    ----------
    client : ClientZotero ou None
    parametres : dict
    confirmation : str
        Doit valoir le mot de confirmation de la configuration.
    essai : bool
        Compte sans supprimer.

    Renvoie
    -------
    int
        Éléments supprimés (ou qui le seraient).

    Lève
    ----
    ConfirmationManquante
        Sans le mot de confirmation.
    """
    if confirmation != parametres["mot_de_confirmation_purge"]:
        raise ConfirmationManquante(
            "Purge annulée : ajouter --confirmer "
            f"{parametres['mot_de_confirmation_purge']} (opération irréversible)"
        )
    total = 0
    for source in ("/items/top", "/items/trash"):
        try:
            cles = client.cles_elements(source)
        except requests.HTTPError:
            continue
        if essai:
            total += len(cles)
            continue
        for debut in range(0, len(cles), parametres["notices_par_lot"]):
            lot = cles[debut : debut + parametres["notices_par_lot"]]
            client.supprimer(lot)
            total += len(lot)
            time.sleep(parametres["pause_entre_lots"])
    journal.info("Purge%s : %d éléments", " (essai à blanc)" if essai else "", total)
    return total


def executer(configuration: Configuration, chemins: Chemins, arguments: argparse.Namespace) -> dict[str, Any]:
    """Envoie les notices vers Zotero, ou purge la bibliothèque.

    Paramètres
    ----------
    configuration : Configuration
    chemins : Chemins
    arguments : argparse.Namespace

    Renvoie
    -------
    dict

    Lève
    ----
    ValueError
        Si la clé ou l'identifiant de bibliothèque manque hors essai à blanc.
    """
    parametres = configuration.plateformes["zotero"]
    cle = valeur_secrete(arguments.cle, "ZOTERO_API_KEY")
    bibliotheque = valeur_secrete(arguments.bibliotheque, "ZOTERO_LIBRARY_ID")
    besoin_client = arguments.purge or not arguments.essai_a_blanc
    if besoin_client and not (cle and bibliotheque):
        raise ValueError(
            "Clé et bibliothèque Zotero obligatoires "
            "(--cle, --bibliotheque, ou ZOTERO_API_KEY, ZOTERO_LIBRARY_ID)"
        )
    client = (
        ClientZotero(cle, arguments.type_bibliotheque, bibliotheque, parametres) if besoin_client else None
    )
    if arguments.purge:
        return {"purges": purger(client, parametres, arguments.confirmer or "", arguments.essai_a_blanc)}

    fichier = arguments.fichier or chemins.sortie("dedoublonnage_annotees")
    notices = notices_a_envoyer(
        lire_csv_texte(fichier).to_dict("records"), arguments.par_oeuvre, arguments.filtre_sig
    )
    if arguments.essai_a_blanc:
        if notices:
            journal.info(
                "Exemple d'élément :\n%s",
                json.dumps(
                    element_zotero(notices[0], parametres, arguments.collection), ensure_ascii=False, indent=2
                ),
            )
        journal.info("%d notices seraient envoyées", len(notices))
        return {"a_envoyer": len(notices)}
    presents = client.identifiants_presents()
    notices = [n for n in notices if n["id_biblio"] not in presents]
    if arguments.limite:
        notices = notices[: arguments.limite]
    creees = echecs = 0
    for debut in range(0, len(notices), parametres["notices_par_lot"]):
        lot = notices[debut : debut + parametres["notices_par_lot"]]
        reponse = client.creer([element_zotero(n, parametres, arguments.collection) for n in lot])
        creees += len(reponse.get("success", {}))
        for rang, erreur in reponse.get("failed", {}).items():
            echecs += 1
            journal.warning("Échec %s : %s", lot[int(rang)].get("id_biblio"), erreur)
        time.sleep(parametres["pause_entre_lots"])
    journal.info("Zotero : %d créées, %d échecs", creees, echecs)
    return {"creees": creees, "echecs": echecs, "deja_presentes": len(presents)}
