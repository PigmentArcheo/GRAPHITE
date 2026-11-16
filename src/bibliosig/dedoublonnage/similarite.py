"""Seconde passe : rapprochement des œuvres aux titres très semblables."""

from __future__ import annotations

import logging
import re
from typing import Any

import numpy as np
from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from bibliosig.configuration import Configuration
from bibliosig.dedoublonnage.notices import NoticeComparee

journal = logging.getLogger(__name__)


def similarite_textes(premier: str, second: str) -> float:
    """Similarité de deux textes normalisés, mots triés, entre 0 et 1.

    Paramètres
    ----------
    premier, second : str

    Renvoie
    -------
    float
    """
    if not premier or not second:
        return 0.0
    return fuzz.token_sort_ratio(premier, second) / 100.0


def score_paire(
    premiere: NoticeComparee, seconde: NoticeComparee, configuration: Configuration
) -> tuple[float, str]:
    """Score de similarité d'une paire : titre seul, ou titre et auteurs.

    Un titre court ou générique ne suffit pas à reconnaître une œuvre : il est
    alors pondéré avec la liste des auteurs.

    Paramètres
    ----------
    premiere, seconde : NoticeComparee
    configuration : Configuration

    Renvoie
    -------
    score : float
    mode : {"titre", "composite"}
    """
    parametres = configuration.chaine["dedoublonnage"]
    similarite_titre = similarite_textes(premiere.titre_normalise, seconde.titre_normalise)
    if premiere.titre_generique or seconde.titre_generique:
        similarite_auteurs = similarite_textes(premiere.auteurs_normalises, seconde.auteurs_normalises)
        score = (
            parametres["poids_titre_composite"] * similarite_titre
            + parametres["poids_auteurs_composite"] * similarite_auteurs
        )
        return score, "composite"
    return similarite_titre, "titre"


def motif_compagnons(configuration: Configuration) -> re.Pattern[str]:
    """Expression des mots d'un objet compagnon (jeu de données, erratum…).

    Paramètres
    ----------
    configuration : Configuration

    Renvoie
    -------
    re.Pattern
    """
    mots = configuration.filtres["dedoublonnage"]["mots_compagnons"]
    return re.compile(r"\b(" + "|".join(mots) + r")\b", re.IGNORECASE)


def est_paire_compagnon(premier_titre: str, second_titre: str, configuration: Configuration) -> bool:
    """Reconnaît « X » face à « Dataset from X » ou « Erratum to X ».

    Paramètres
    ----------
    premier_titre, second_titre : str
        Titres bruts.
    configuration : Configuration

    Renvoie
    -------
    bool
        Vrai si les deux notices ne doivent pas être fusionnées.
    """
    if not premier_titre or not second_titre:
        return False
    parametres = configuration.chaine["dedoublonnage"]
    motif = motif_compagnons(configuration)
    court, long = (
        (premier_titre, second_titre)
        if len(premier_titre) <= len(second_titre)
        else (second_titre, premier_titre)
    )
    if (
        long.startswith(court)
        and len(long) - len(court) >= parametres["longueur_min_complement_compagnon"]
        and motif.search(long[len(court) :])
    ):
        return True
    return bool(motif.search(long[: parametres["longueur_debut_titre_compagnon"]]) and court in long)


def paires_candidates(
    notices: dict[str, NoticeComparee], configuration: Configuration
) -> list[tuple[str, str]]:
    """Paires de notices aux titres proches, par similarité cosinus de n-grammes.

    La matrice est calculée par lots de lignes pour borner la mémoire ; chaque
    ligne est identique à celle de la matrice complète.

    Paramètres
    ----------
    notices : dict
        id_biblio vers NoticeComparee.
    configuration : Configuration

    Renvoie
    -------
    list of tuple
        Paires (id_biblio, id_biblio), dans l'ordre des lignes puis des colonnes.
    """
    parametres = configuration.chaine["dedoublonnage"]
    avec_titre = [notice for notice in notices.values() if notice.titre_normalise]
    if len(avec_titre) < 2:
        return []
    vectoriseur = TfidfVectorizer(
        analyzer=parametres["analyseur_tfidf"],
        ngram_range=tuple(parametres["ngrammes_tfidf"]),
        min_df=parametres["frequence_min_tfidf"],
        max_df=parametres["frequence_max_tfidf"],
    )
    try:
        matrice = vectoriseur.fit_transform([notice.titre_normalise for notice in avec_titre])
    except ValueError as erreur:
        journal.warning("Vectorisation des titres impossible : %s", erreur)
        return []

    seuil = parametres["seuil_cosinus_blocage"]
    taille_lot = parametres["lignes_par_lot_cosinus"]
    nombre = matrice.shape[0]
    candidates: list[tuple[str, str]] = []
    for debut in range(0, nombre, taille_lot):
        bloc = cosine_similarity(matrice[debut : debut + taille_lot], matrice)
        for decalage, ligne in enumerate(bloc):
            rang = debut + decalage
            voisins = np.where(ligne[rang + 1 :] >= seuil)[0] + rang + 1
            identifiant = avec_titre[rang].id_biblio
            candidates.extend((identifiant, avec_titre[voisin].id_biblio) for voisin in voisins)
    journal.info("%d paires candidates après blocage", len(candidates))
    return candidates


def fusionner_oeuvres(oeuvre_par_notice: dict[str, str], premiere: str, seconde: str) -> None:
    """Réunit deux œuvres sous le plus petit des deux identifiants.

    Paramètres
    ----------
    oeuvre_par_notice : dict
        Modifié sur place.
    premiere, seconde : str
        Identifiants des deux œuvres.
    """
    cible, absorbee = min(premiere, seconde), max(premiere, seconde)
    for identifiant, oeuvre in oeuvre_par_notice.items():
        if oeuvre == absorbee:
            oeuvre_par_notice[identifiant] = cible


def regrouper_par_similarite(
    notices: dict[str, NoticeComparee],
    oeuvre_par_notice: dict[str, str],
    configuration: Configuration,
    seuil_titre: float,
) -> list[dict[str, Any]]:
    """Fusionne les œuvres dont les titres sont très semblables.

    Paramètres
    ----------
    notices : dict
        id_biblio vers NoticeComparee.
    oeuvre_par_notice : dict
        id_biblio vers œuvre ; modifié sur place.
    configuration : Configuration
    seuil_titre : float
        Score minimal pour fusionner.

    Renvoie
    -------
    list of dict
        Journal des paires examinées au-dessus du seuil, avec leur verdict.
    """
    parametres = configuration.chaine["dedoublonnage"]
    journal_paires: list[dict[str, Any]] = []
    for premier_id, second_id in paires_candidates(notices, configuration):
        if oeuvre_par_notice[premier_id] == oeuvre_par_notice[second_id]:
            continue
        premiere, seconde = notices[premier_id], notices[second_id]
        score, mode = score_paire(premiere, seconde, configuration)
        if score < seuil_titre:
            continue
        if (
            premiere.annee
            and seconde.annee
            and abs(premiere.annee - seconde.annee) > parametres["ecart_max_annees"]
        ):
            continue
        entree = {"id1": premier_id, "id2": second_id, "score": round(score, 3)}
        if est_paire_compagnon(premiere.titre, seconde.titre, configuration):
            journal_paires.append({**entree, "mode": "compagnon_rejeté", "verdict": "non_fusionné"})
            continue
        # Garde-fou des DOI : sous le seuil, seuls deux DOI présents et égaux
        # autorisent la fusion. Un DOI absent est une valeur manquante, jamais égale
        # à un autre DOI : une notice sans DOI ne fusionne donc qu'au-dessus du seuil.
        dois_egaux = premiere.doi_normalise is not None and premiere.doi_normalise == seconde.doi_normalise
        if not dois_egaux and score < parametres["seuil_fusion_malgre_dois_differents"]:
            journal_paires.append({**entree, "mode": "dois_différents", "verdict": "non_fusionné"})
            continue
        fusionner_oeuvres(oeuvre_par_notice, oeuvre_par_notice[premier_id], oeuvre_par_notice[second_id])
        journal_paires.append({**entree, "mode": mode, "verdict": "fusionné"})
    return journal_paires
