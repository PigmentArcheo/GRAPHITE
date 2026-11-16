"""Regroupements approchés des formes de noms : même œuvre, précoce, co-auteurs, famille."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence

import pandas as pd
from rapidfuzz import fuzz

from bibliosig.auteurs.noms import normaliser_forme, richesse_unicode

journal = logging.getLogger(__name__)


def separer_auteurs(champ: str, separateur: str) -> list[str]:
    """Liste des formes non vides d'un champ auteurs.

    Paramètres
    ----------
    champ : str
    separateur : str

    Renvoie
    -------
    list of str
    """
    return [forme.strip() for forme in champ.split(separateur) if forme.strip()]


def fusions_meme_oeuvre(notices: pd.DataFrame, seuil: float, separateur: str) -> dict[str, str]:
    """Rapproche les formes presque identiques entre les notices d'une même œuvre.

    Deux portails qui décrivent la même publication citent les mêmes personnes :
    « Alice Durand » et « Durand Alice » dans la même œuvre sont une seule personne.

    Paramètres
    ----------
    notices : pandas.DataFrame
        Notices avec ``work_cluster_id`` et ``auteurs``.
    seuil : float
        Similarité minimale (mots triés), entre 0 et 1.
    separateur : str

    Renvoie
    -------
    dict
        Forme absorbée vers forme retenue.
    """
    if "work_cluster_id" not in notices.columns:
        journal.warning("Colonne work_cluster_id absente : passe « même œuvre » ignorée")
        return {}
    seuil_pourcent = int(seuil * 100)
    auteurs_par_oeuvre: dict[str, list[list[str]]] = defaultdict(list)
    for oeuvre, champ in zip(notices["work_cluster_id"], notices["auteurs"], strict=True):
        oeuvre = oeuvre.strip()
        if oeuvre and champ and champ != "nan":
            formes = separer_auteurs(champ, separateur)
            if formes:
                auteurs_par_oeuvre[oeuvre].append(formes)
    journal.info(
        "Œuvres à plusieurs notices : %d sur %d",
        sum(1 for listes in auteurs_par_oeuvre.values() if len(listes) > 1),
        len(auteurs_par_oeuvre),
    )
    fusions: dict[str, str] = {}
    for listes in auteurs_par_oeuvre.values():
        for rang, premiere_liste in enumerate(listes):
            for seconde_liste in listes[rang + 1 :]:
                for premiere in premiere_liste:
                    for seconde in seconde_liste:
                        if premiere == seconde:
                            continue
                        similarite = fuzz.token_sort_ratio(
                            normaliser_forme(premiere), normaliser_forme(seconde)
                        )
                        if similarite >= seuil_pourcent:
                            enregistrer_fusion(fusions, premiere, seconde)
    return fusions


def enregistrer_fusion(fusions: dict[str, str], premiere: str, seconde: str) -> None:
    """Ajoute une fusion en gardant les chaînes de fusions résolues.

    La forme la plus riche en lettres accentuées devient la référence, puis la
    plus longue l'emporte entre deux références déjà établies.

    Paramètres
    ----------
    fusions : dict
        Modifié sur place.
    premiere, seconde : str
    """
    retenue = premiere if richesse_unicode(premiere) >= richesse_unicode(seconde) else seconde
    absorbee = seconde if retenue == premiere else premiere
    reference_retenue = fusions.get(retenue, retenue)
    reference_absorbee = fusions.get(absorbee, absorbee)
    if reference_retenue == reference_absorbee:
        return
    finale = reference_retenue if len(reference_retenue) >= len(reference_absorbee) else reference_absorbee
    perdante = reference_absorbee if finale == reference_retenue else reference_retenue
    fusions[perdante] = finale
    for forme, cible in list(fusions.items()):
        if cible == perdante:
            fusions[forme] = finale


def resoudre_reference(forme: str, fusions: dict[str, str]) -> str:
    """Suit la chaîne des fusions jusqu'à la forme de référence.

    Paramètres
    ----------
    forme : str
    fusions : dict

    Renvoie
    -------
    str
    """
    vues = set()
    while forme in fusions and forme not in vues:
        vues.add(forme)
        forme = fusions[forme]
    return forme


def regrouper_precocement(formes: Sequence[str], seuil: float) -> list[list[str]]:
    """Regroupe les formes de noms normalisés semblables, mots triés, avant tout blocage.

    Paramètres
    ----------
    formes : liste de str
    seuil : float
        Similarité minimale, entre 0 et 1.

    Renvoie
    -------
    list of list of str
        Groupes, dans l'ordre de la première forme de chacun.
    """
    normalisees = [normaliser_forme(forme) for forme in formes]
    seuil_pourcent = int(seuil * 100)
    groupes: list[list[str]] = []
    utilisees: set[int] = set()
    for rang, forme in enumerate(formes):
        if rang in utilisees:
            continue
        groupe = [forme]
        utilisees.add(rang)
        for autre_rang in range(len(formes)):
            if autre_rang in utilisees:
                continue
            if fuzz.token_sort_ratio(normalisees[rang], normalisees[autre_rang]) >= seuil_pourcent:
                groupe.append(formes[autre_rang])
                utilisees.add(autre_rang)
        groupes.append(groupe)
    return groupes


def regrouper_dans_famille(formes: Sequence[str], seuil: float) -> list[list[str]]:
    """Regroupe, dans une famille de noms, les formes brutes très semblables.

    Paramètres
    ----------
    formes : liste de str
    seuil : float

    Renvoie
    -------
    list of list of str
    """
    if not formes:
        return []
    if len(formes) == 1:
        return [list(formes)]
    seuil_pourcent = int(seuil * 100)
    groupes: list[list[str]] = []
    utilisees: set[str] = set()
    for forme in formes:
        if forme in utilisees:
            continue
        groupe = [forme]
        utilisees.add(forme)
        for autre in formes:
            if autre in utilisees or autre == forme:
                continue
            if fuzz.ratio(forme, autre) >= seuil_pourcent:
                groupe.append(autre)
                utilisees.add(autre)
        groupes.append(groupe)
    return groupes


def jaccard(premier: set[str], second: set[str]) -> float:
    """Indice de Jaccard de deux ensembles (0 si l'un est vide).

    Paramètres
    ----------
    premier, second : set of str

    Renvoie
    -------
    float
    """
    if not premier or not second:
        return 0.0
    union = len(premier | second)
    return len(premier & second) / union if union else 0.0


def regrouper_par_coauteurs(
    formes: Sequence[str],
    coauteurs: dict[str, set[str]],
    communs_min: int,
    jaccard_min: float,
    seuil_nom: float,
) -> list[list[str]]:
    """Regroupe des formes au nom proche qui partagent des co-auteurs.

    Les deux conditions sont exigées : sans la ressemblance des noms, on
    fusionnerait simplement des personnes qui publient ensemble.

    Paramètres
    ----------
    formes : liste de str
    coauteurs : dict
        Forme vers ensemble des co-auteurs normalisés.
    communs_min : int
        Nombre minimal de co-auteurs communs.
    jaccard_min : float
        Indice de Jaccard minimal des co-auteurs.
    seuil_nom : float
        Similarité minimale des noms (mots triés), entre 0 et 1.

    Renvoie
    -------
    list of list of str
    """
    if len(formes) <= 1:
        return [[forme] for forme in formes]
    seuil_pourcent = int(seuil_nom * 100)
    normalisees = {forme: normaliser_forme(forme) for forme in formes}
    groupes: list[list[str]] = []
    utilisees: set[str] = set()
    for forme in formes:
        if forme in utilisees:
            continue
        groupe = [forme]
        utilisees.add(forme)
        coauteurs_forme = coauteurs.get(forme, set())
        for autre in formes:
            if autre in utilisees or autre == forme:
                continue
            if fuzz.token_sort_ratio(normalisees[forme], normalisees[autre]) < seuil_pourcent:
                continue
            coauteurs_autre = coauteurs.get(autre, set())
            if not coauteurs_autre:
                continue
            if (
                len(coauteurs_forme & coauteurs_autre) >= communs_min
                and jaccard(coauteurs_forme, coauteurs_autre) >= jaccard_min
            ):
                groupe.append(autre)
                utilisees.add(autre)
        groupes.append(groupe)
    return groupes
