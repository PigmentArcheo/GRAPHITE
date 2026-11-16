"""Publications par plateforme, par année et par concept, et co-occurrences de concepts.

Les requêtes Cypher équivalentes sont dans ``requetes/publications_concepts.cypher``.
"""

from __future__ import annotations

import pandas as pd

from bibliosig.analyses.graphe_csv import GrapheTables


def notices_par_portail_et_annee(
    graphe: GrapheTables, premiere_annee: int, derniere_annee: int
) -> pd.DataFrame:
    """Nombre de notices par plateforme et par année.

    Paramètres
    ----------
    graphe : GrapheTables
    premiere_annee, derniere_annee : int
        Bornes incluses.

    Renvoie
    -------
    pandas.DataFrame
        Colonnes ``portal``, ``year``, ``nb_records``, triées par plateforme et année.
    """
    jointure = graphe.portails.merge(graphe.notices, left_on="record_id", right_on="id_biblio")
    jointure = jointure[jointure["year"].between(premiere_annee, derniere_annee)]
    return (
        jointure.groupby(["portal", "year"])
        .size()
        .rename("nb_records")
        .reset_index()
        .sort_values(["portal", "year"])
        .reset_index(drop=True)
    )


def oeuvres_par_concept_et_annee(graphe: GrapheTables, premiere_annee: int) -> pd.DataFrame:
    """Œuvres distinctes par concept (A ou B) et par année de notice.

    Paramètres
    ----------
    graphe : GrapheTables
    premiere_annee : int
        Pas de borne haute : toutes les années à partir de celle-ci sont comptées.

    Renvoie
    -------
    pandas.DataFrame
        Colonnes ``year``, ``concept``, ``nbWorks``, triées par année puis effectif décroissant.
    """
    concepts = pd.concat(
        [graphe.concepts_a[["record_id", "label"]], graphe.concepts_b[["record_id", "label"]]]
    )
    jointure = graphe.representations.merge(graphe.notices, left_on="record_id", right_on="id_biblio").merge(
        concepts, on="record_id"
    )
    jointure = jointure[jointure["year"] >= premiere_annee]
    resultat = (
        jointure.groupby(["year", "label"])["work_key"]
        .nunique()
        .rename("nbWorks")
        .reset_index()
        .rename(columns={"label": "concept"})
    )
    return resultat.sort_values(["year", "nbWorks"], ascending=[True, False]).reset_index(drop=True)


def co_occurrences_concepts(graphe: GrapheTables) -> pd.DataFrame:
    """Œuvres distinctes où un concept A et un concept B sont associés.

    Paramètres
    ----------
    graphe : GrapheTables

    Renvoie
    -------
    pandas.DataFrame
        Colonnes ``conceptA``, ``labelA``, ``conceptB``, ``labelB``, ``weight``.
    """
    jointure = graphe.representations.merge(graphe.concepts_a, on="record_id").merge(
        graphe.concepts_b, on="record_id", suffixes=("_a", "_b")
    )
    resultat = (
        jointure.groupby(["concept_code_a", "label_a", "concept_code_b", "label_b"])["work_key"]
        .nunique()
        .rename("weight")
        .reset_index()
        .rename(
            columns={
                "concept_code_a": "conceptA",
                "label_a": "labelA",
                "concept_code_b": "conceptB",
                "label_b": "labelB",
            }
        )
    )
    return resultat.sort_values("weight", ascending=False).reset_index(drop=True)


def oeuvres_par_annee(graphe: GrapheTables, premiere_annee: int, derniere_annee: int) -> pd.DataFrame:
    """Publications uniques (œuvres distinctes) par année de notice.

    Paramètres
    ----------
    graphe : GrapheTables
    premiere_annee, derniere_annee : int

    Renvoie
    -------
    pandas.DataFrame
        Colonnes ``year``, ``nbWorks``.
    """
    jointure = graphe.representations.merge(graphe.notices, left_on="record_id", right_on="id_biblio")
    jointure = jointure[jointure["year"].between(premiere_annee, derniere_annee)]
    return (
        jointure.groupby("year")["work_key"]
        .nunique()
        .rename("nbWorks")
        .reset_index()
        .sort_values("year")
        .reset_index(drop=True)
    )
