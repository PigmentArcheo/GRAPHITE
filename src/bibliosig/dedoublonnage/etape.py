"""Étape « dedoublonne » : notices regroupées en œuvres, une notice gardée par œuvre."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import pandas as pd

from bibliosig.communs.tableaux import (
    ecrire_bilan,
    ecrire_csv,
    ecrire_json,
    lire_csv_texte,
    texte_avec_nan,
)
from bibliosig.configuration import Chemins, Configuration
from bibliosig.dedoublonnage.arbitrage import arbitrer_paires
from bibliosig.dedoublonnage.identifiants import regrouper_par_identifiants
from bibliosig.dedoublonnage.notices import preparer_notices
from bibliosig.dedoublonnage.similarite import regrouper_par_similarite
from bibliosig.llm.ollama import ClientOllama

journal = logging.getLogger(__name__)


def choisir_notices_preferees(
    notices: pd.DataFrame,
    oeuvre_par_notice: dict[str, str],
    priorite_par_notice: dict[str, int],
    configuration: Configuration,
) -> pd.DataFrame:
    """Garde une notice par œuvre : portail prioritaire, puis notice la plus remplie.

    Paramètres
    ----------
    notices : pandas.DataFrame
    oeuvre_par_notice : dict
        id_biblio vers œuvre.
    priorite_par_notice : dict
        id_biblio vers priorité du portail (0 = préféré).
    configuration : Configuration

    Renvoie
    -------
    pandas.DataFrame
        Notices gardées, avec ``work_cluster_id``, ``nb_notices_cluster`` et
        ``portails_src`` (portails de l'œuvre).
    """
    colonnes_richesse = configuration.chaine["dedoublonnage"]["colonnes_richesse"]
    travail = notices.copy()
    travail["_oeuvre"] = travail["id_biblio"].map(oeuvre_par_notice)
    travail["_priorite"] = travail["id_biblio"].map(priorite_par_notice)
    travail["_richesse"] = (travail[colonnes_richesse] != "").sum(axis=1)
    preferees = (
        travail.sort_values(by=["_oeuvre", "_priorite", "_richesse"], ascending=[True, True, False])
        .drop_duplicates(subset="_oeuvre", keep="first")
        .copy()
    )
    preferees["work_cluster_id"] = preferees["_oeuvre"]
    preferees["nb_notices_cluster"] = preferees["_oeuvre"].map(travail["_oeuvre"].value_counts())
    portails_par_oeuvre = travail.groupby("_oeuvre")["portail"].apply(
        lambda portails: " | ".join(sorted({portail for portail in portails if portail != ""}))
    )
    preferees["portails_src"] = preferees["_oeuvre"].map(portails_par_oeuvre)
    return preferees


def description_oeuvres(
    notices: pd.DataFrame, oeuvre_par_notice: dict[str, str], configuration: Configuration
) -> dict[str, dict[str, Any]]:
    """Décrit chaque œuvre : membres, portails et titre représentatif.

    Paramètres
    ----------
    notices : pandas.DataFrame
    oeuvre_par_notice : dict
    configuration : Configuration

    Renvoie
    -------
    dict
        Identifiant d'œuvre vers description, pour ``work_clusters.json``.
    """
    longueur_titre = configuration.chaine["dedoublonnage"]["longueur_titre_representatif"]
    membres_par_oeuvre: dict[str, list[str]] = defaultdict(list)
    for identifiant, oeuvre in oeuvre_par_notice.items():
        membres_par_oeuvre[oeuvre].append(identifiant)
    portail_par_notice = dict(zip(notices["id_biblio"], notices["portail"], strict=True))
    titre_par_notice = dict(zip(notices["id_biblio"], notices["titre"], strict=True))
    description = {}
    for oeuvre, membres in membres_par_oeuvre.items():
        description[oeuvre] = {
            "members": sorted(membres),
            "n": len(membres),
            "portails": sorted(
                {texte_avec_nan(portail_par_notice.get(membre, "")) for membre in membres}
            ),
            "titre_repr": texte_avec_nan(titre_par_notice.get(membres[0], ""))[:longueur_titre],
        }
    return description


def executer(
    configuration: Configuration,
    chemins: Chemins,
    utiliser_llm: bool = False,
    rejouer: bool = False,
    seuil_titre: float | None = None,
) -> dict[str, Any]:
    """Dédoublonne les notices gardées par les filtres.

    Paramètres
    ----------
    configuration : Configuration
    chemins : Chemins
    utiliser_llm : bool
        Soumet les paires de score intermédiaire au modèle de langue.
    rejouer : bool
        Sans appel au modèle : son avis ne modifie pas les œuvres (il est
        seulement consigné), les sorties sont donc les mêmes.
    seuil_titre : float, optionnel
        Remplace le seuil de similarité de la configuration.

    Renvoie
    -------
    dict
        Bilan : notices en entrée et gardées, groupes par identifiant, fusions.
    """
    parametres = configuration.chaine["dedoublonnage"]
    seuil = seuil_titre if seuil_titre is not None else parametres["seuil_similarite_titre"]
    notices = lire_csv_texte(chemins.sortie("filtre_positif_gardees"))
    comparees = preparer_notices(notices, configuration)

    oeuvre_par_notice, journal_groupes = regrouper_par_identifiants(comparees, configuration)
    journal.info(
        "Passe 1 : %d groupes, %d œuvres",
        len(journal_groupes),
        len(set(oeuvre_par_notice.values())),
    )
    journal_paires = regrouper_par_similarite(comparees, oeuvre_par_notice, configuration, seuil)
    fusions = sum(1 for entree in journal_paires if entree["verdict"] == "fusionné")
    journal.info("Passe 2 : %d fusions, %d œuvres", fusions, len(set(oeuvre_par_notice.values())))

    avis_llm: list[dict[str, Any]] = []
    if utiliser_llm and rejouer:
        journal.info("Mode rejeu : avis du modèle non demandé (sans effet sur les œuvres)")
    elif utiliser_llm:
        client = ClientOllama(configuration)
        client.verifier()
        avis_llm = arbitrer_paires(
            comparees, journal_paires, configuration, client, parametres["seuil_confiance_llm"]
        )

    priorites = {identifiant: notice.priorite_portail for identifiant, notice in comparees.items()}
    preferees = choisir_notices_preferees(notices, oeuvre_par_notice, priorites, configuration)
    colonnes = [c for c in configuration.chaine["schema"]["colonnes"] if c in preferees.columns]
    ecrire_csv(
        preferees[[*colonnes, "work_cluster_id", "nb_notices_cluster", "portails_src"]],
        chemins.sortie("dedoublonnage_notices"),
    )
    annotees = notices.copy()
    annotees["work_cluster_id"] = annotees["id_biblio"].map(oeuvre_par_notice)
    ecrire_csv(annotees, chemins.sortie("dedoublonnage_annotees"))
    oeuvres = description_oeuvres(notices, oeuvre_par_notice, configuration)
    ecrire_json(oeuvres, chemins.sortie("dedoublonnage_oeuvres"))

    bilan = {
        "entree": len(notices),
        "gardees": len(preferees),
        "groupes_par_identifiant": len(journal_groupes),
        "fusions_par_similarite": fusions,
        "paires_non_fusionnees": len(journal_paires) - fusions,
        "oeuvres_multi_notices": sum(1 for oeuvre in oeuvres.values() if oeuvre["n"] > 1),
        "paires_a_arbitrer": sum(
            1
            for entree in journal_paires
            if parametres["borne_basse_arbitrage"] <= entree["score"] < parametres["borne_haute_arbitrage"]
        ),
        "avis_llm": avis_llm,
    }
    ecrire_bilan(chemins.sortie("dossier_bilans"), "dedoublonnage", bilan)
    return bilan
