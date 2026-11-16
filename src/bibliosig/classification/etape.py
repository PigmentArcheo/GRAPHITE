"""Étape « classe » : garde les œuvres où le SIG est un outil ou une méthode centrale."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from bibliosig.classification.decisions import (
    Decision,
    motif_prefiltre,
    prefiltrer,
)
from bibliosig.classification.modele import PointDeReprise, classer_notices
from bibliosig.communs.tableaux import ecrire_bilan, ecrire_csv, lire_csv_texte
from bibliosig.configuration import Chemins, Configuration
from bibliosig.llm.ollama import ClientOllama
from bibliosig.normalisation.corrections import appliquer_corrections_fichier

journal = logging.getLogger(__name__)

CLES_SORTIES = ("classification_gardees", "classification_rejetees", "classification_a_relire")


def destinations(decision: Decision, configuration: Configuration) -> set[str]:
    """Fichiers de sortie d'une décision selon les seuils de confiance.

    Paramètres
    ----------
    decision : Decision
    configuration : Configuration

    Renvoie
    -------
    set of str
        Clés des sorties : gardées (SIG assez sûr), rejetées (hors SIG),
        à relire (confiance faible) ; une notice peut être rejetée et à relire.
    """
    parametres = configuration.chaine["classification"]
    a_relire = decision.confiance < parametres["seuil_relecture"]
    cles = set()
    if decision.label == "sig" and decision.confiance >= parametres["seuil_confiance"] and not a_relire:
        cles.add("classification_gardees")
    if decision.label == "hors_sig":
        cles.add("classification_rejetees")
    if a_relire:
        cles.add("classification_a_relire")
    return cles


def lire_repartition_enregistree(
    configuration: Configuration, dossier: Path
) -> tuple[dict[str, Decision], dict[str, set[str]]]:
    """Relit les décisions et la sortie où chaque notice a été rangée.

    Paramètres
    ----------
    configuration : Configuration
    dossier : Path
        Dossier des sorties d'une classification déjà faite.

    Renvoie
    -------
    decisions : dict
        id_biblio vers Decision ; pour une notice présente dans plusieurs
        sorties, la première lue (gardées, rejetées, à relire).
    rangements : dict
        id_biblio vers clés des sorties qui contiennent la notice.

    Lève
    ----
    FileNotFoundError
        Si aucune sortie n'existe dans le dossier.
    """
    noms = Chemins(dossier, dossier, configuration.chaine["fichiers"])
    decisions: dict[str, Decision] = {}
    rangements: dict[str, set[str]] = {}
    for cle in CLES_SORTIES:
        chemin = noms.sortie(cle)
        if not chemin.exists():
            continue
        for ligne in lire_csv_texte(chemin).itertuples(index=False):
            try:
                confiance = float(ligne.llm_confiance or 0.0)
            except ValueError:
                confiance = 0.0
            decisions.setdefault(ligne.id_biblio, Decision(ligne.llm_label, confiance, ligne.llm_raison))
            rangements.setdefault(ligne.id_biblio, set()).add(cle)
    if not decisions:
        raise FileNotFoundError(f"Aucune décision de classification à rejouer dans {dossier}")
    journal.info("%d décisions relues dans %s", len(decisions), dossier)
    return decisions, rangements


def rejouer_classification(
    notices: pd.DataFrame, configuration: Configuration, dossier_decisions: Path
) -> tuple[dict[str, Decision], dict[str, int]]:
    """Reprend les décisions enregistrées, en recalculant le pré-filtre.

    Les seuils rangent ensuite chaque notice. Une notice rangée autrement que
    dans les sorties relues signale une retouche manuelle faite après la
    classification : elle est comptée, et la retouche relève du fichier des
    corrections manuelles.

    Paramètres
    ----------
    notices : pandas.DataFrame
    configuration : Configuration
    dossier_decisions : Path

    Renvoie
    -------
    decisions : dict
    controles : dict
        Comptes de cohérence entre pré-filtre, décisions et sorties.
    """
    enregistrees, rangements = lire_repartition_enregistree(configuration, dossier_decisions)
    motif = motif_prefiltre(configuration)
    raison_prefiltre = configuration.filtres["prefiltre_sig"]["raison"]
    decisions: dict[str, Decision] = {}
    controles = {
        "prefiltre": 0,
        "prefiltre_non_enregistre": 0,
        "decisions_modele": 0,
        "sans_decision": 0,
        "rangements_differents": 0,
        "hors_entree": len(set(enregistrees) - set(notices["id_biblio"])),
    }
    for _, notice in notices.iterrows():
        identifiant = notice["id_biblio"]
        decision_prefiltre = prefiltrer(notice, motif, configuration)
        enregistree = enregistrees.get(identifiant)
        if decision_prefiltre is not None:
            controles["prefiltre"] += 1
            if enregistree is None or enregistree.raison != raison_prefiltre:
                controles["prefiltre_non_enregistre"] += 1
            decisions[identifiant] = decision_prefiltre
        elif enregistree is not None:
            controles["decisions_modele"] += 1
            decisions[identifiant] = enregistree
        else:
            controles["sans_decision"] += 1
            continue
        if destinations(decisions[identifiant], configuration) != rangements.get(identifiant, set()):
            controles["rangements_differents"] += 1
            journal.warning("Rangement différent de la sortie relue : %s", identifiant)
    return decisions, controles


def classer_en_direct(
    notices: pd.DataFrame,
    configuration: Configuration,
    chemins: Chemins,
    avec_prefiltre: bool,
) -> dict[str, Decision]:
    """Classe les notices : pré-filtre, puis modèle de langue pour les autres.

    Paramètres
    ----------
    notices : pandas.DataFrame
    configuration : Configuration
    chemins : Chemins
    avec_prefiltre : bool

    Renvoie
    -------
    dict
        id_biblio vers Decision.
    """
    parametres = configuration.chaine["classification"]
    reprise = PointDeReprise(chemins.sortie("classification_reprise"), parametres["notices_par_sauvegarde"])
    motif = motif_prefiltre(configuration)
    a_soumettre = []
    for _, notice in notices.iterrows():
        if notice["id_biblio"] in reprise.decisions:
            continue
        decision = prefiltrer(notice, motif, configuration) if avec_prefiltre else None
        if decision is not None:
            reprise.ajouter(notice["id_biblio"], decision)
        else:
            a_soumettre.append(notice)
    journal.info("%d notices soumises au modèle", len(a_soumettre))
    if a_soumettre:
        client = ClientOllama(configuration)
        client.verifier()
        classer_notices(a_soumettre, client, reprise, configuration)
    reprise.sauvegarder()
    return reprise.decisions


def executer(
    configuration: Configuration,
    chemins: Chemins,
    rejouer: bool = False,
    dossier_decisions: Path | None = None,
    limite: int | None = None,
    avec_prefiltre: bool = True,
) -> dict[str, Any]:
    """Classe les œuvres dédoublonnées et écrit les trois sorties.

    Paramètres
    ----------
    configuration : Configuration
    chemins : Chemins
    rejouer : bool
        Relit les décisions déjà prises au lieu d'appeler le modèle.
    dossier_decisions : Path, optionnel
        Dossier des sorties à rejouer ; par défaut le dossier des sorties.
    limite : int, optionnel
        Ne traite que les premières notices (essai).
    avec_prefiltre : bool
        Applique le pré-filtre par motifs avant le modèle.

    Renvoie
    -------
    dict
        Bilan : effectif de chaque sortie et contrôles du rejeu.
    """
    notices = lire_csv_texte(chemins.sortie("dedoublonnage_notices"))
    if limite is not None:
        notices = notices.head(limite)
    controles: dict[str, int] = {}
    if rejouer:
        decisions, controles = rejouer_classification(
            notices, configuration, dossier_decisions or chemins.sorties
        )
    else:
        decisions = classer_en_direct(notices, configuration, chemins, avec_prefiltre)
    rangements = {
        identifiant: destinations(decision, configuration) for identifiant, decision in decisions.items()
    }

    classees = notices[notices["id_biblio"].isin(decisions)].copy()
    classees["llm_label"] = classees["id_biblio"].map(lambda cle: decisions[cle].label)
    classees["llm_confiance"] = classees["id_biblio"].map(lambda cle: decisions[cle].confiance)
    classees["llm_raison"] = classees["id_biblio"].map(lambda cle: decisions[cle].raison)
    bilan: dict[str, Any] = {"entree": len(notices), "controles_rejeu": controles}
    for cle in CLES_SORTIES:
        dans_sortie = classees["id_biblio"].map(lambda identifiant, cle=cle: cle in rangements[identifiant])
        sortie = classees[dans_sortie]
        chemin = chemins.sortie(cle)
        ecrire_csv(sortie, chemin)
        bilan[cle] = len(appliquer_corrections_fichier(chemin, configuration, chemins))
    bilan["erreurs_modele"] = int((classees["llm_label"] == "erreur").sum())
    reprise = chemins.sortie("classification_reprise")
    if not rejouer and bilan["erreurs_modele"] == 0 and reprise.exists():
        reprise.unlink()
        journal.info("Point de reprise supprimé : aucune erreur du modèle")
    journal.info(
        "Classification : %d gardées, %d rejetées, %d à relire",
        bilan["classification_gardees"],
        bilan["classification_rejetees"],
        bilan["classification_a_relire"],
    )
    ecrire_bilan(chemins.sortie("dossier_bilans"), "classification", bilan)
    return bilan
