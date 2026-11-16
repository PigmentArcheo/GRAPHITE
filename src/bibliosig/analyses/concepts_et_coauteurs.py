"""Parts des mots-clés, associations de concepts, flux et réseau des co-auteurs."""

from __future__ import annotations

import itertools
from typing import Any

import networkx as nx
import pandas as pd

from bibliosig.analyses.graphe_csv import GrapheTables


def parts_mots_cles(
    oeuvres_concepts: pd.DataFrame, parametres: dict[str, Any], annees: range
) -> pd.DataFrame:
    """Part de chaque mot-clé du bloc B dans le total annuel, en pourcentage.

    Paramètres
    ----------
    oeuvres_concepts : pandas.DataFrame
        Sortie de ``oeuvres_par_concept_et_annee``.
    parametres : dict
        Section ``[mots_cles]``.
    annees : range

    Renvoie
    -------
    pandas.DataFrame
        Années en lignes, mots-clés du bloc B en colonnes.
    """
    tableau = oeuvres_concepts.copy()
    tableau["mot_cle"] = tableau["concept"].replace(parametres["fusion_libelles"])
    tableau = tableau[tableau["mot_cle"].isin(parametres["bloc_b"]) & tableau["year"].isin(annees)]
    croise = tableau.pivot_table(
        index="year", columns="mot_cle", values="nbWorks", aggfunc="sum", fill_value=0
    ).reindex(columns=parametres["bloc_b"], fill_value=0)
    return croise.div(croise.sum(axis=1), axis=0) * 100


def chiffres_mots_cles(parts: pd.DataFrame, parametres: dict[str, Any]) -> dict[str, float]:
    """Indicateurs résumés des parts de mots-clés.

    Paramètres
    ----------
    parts : pandas.DataFrame
    parametres : dict

    Renvoie
    -------
    dict
    """
    annee = parametres["annee_citee"]
    if parts.empty or annee not in parts.index:
        return {}
    trio = parts[parametres["trio"]].sum(axis=1)
    innovations = parts[parametres["innovations"]].sum(axis=1)
    premiere, seconde = parametres["premiere_periode_trio"], parametres["seconde_periode_trio"]
    return {
        "part_sig_annee_citee": round(float(parts.loc[annee, "SIG"]), 1),
        "analyse_spatiale_debut": round(float(parts.iloc[0]["analyse spatiale"])),
        "analyse_spatiale_annee_citee": round(float(parts.loc[annee, "analyse spatiale"])),
        "trio_premiere_periode": round(float(trio.loc[premiere[0] : premiere[1]].mean())),
        "trio_seconde_periode": round(float(trio.loc[seconde[0] : seconde[1]].mean())),
        "innovations_maximum": round(float(innovations.max()), 1),
    }


def chiffres_reseau(co_occurrences: pd.DataFrame, parametres: dict[str, Any]) -> dict[str, Any]:
    """Associations dominantes et poids du noyau dans les co-occurrences.

    Paramètres
    ----------
    co_occurrences : pandas.DataFrame
        Sortie de ``co_occurrences_concepts``.
    parametres : dict
        Section ``[reseau]``.

    Renvoie
    -------
    dict
    """
    premieres = co_occurrences.sort_values("weight", ascending=False).head(parametres["associations_citees"])
    noyau = co_occurrences["labelB"].isin(parametres["noyau"])
    return {
        "associations": [
            [concept_a, concept_b, int(poids)]
            for concept_a, concept_b, poids in zip(
                premieres["labelA"], premieres["labelB"], premieres["weight"], strict=True
            )
        ],
        "part_noyau": round(
            float(co_occurrences.loc[noyau, "weight"].sum() / co_occurrences["weight"].sum() * 100), 1
        ),
    }


def liens_sankey(
    graphe: GrapheTables, parametres: dict[str, Any], premiere_annee: int, derniere_annee: int
) -> pd.DataFrame:
    """Flux concept A → couple → concept B, en œuvres distinctes.

    Pour chaque notice, toutes les combinaisons (concept A, couple, concept B)
    sont comptées en œuvres distinctes ; les plus fortes, au-dessus du seuil,
    donnent les liens A → couple et couple → B, sommés.

    Paramètres
    ----------
    graphe : GrapheTables
    parametres : dict
        Section ``[sankey]``.
    premiere_annee, derniere_annee : int

    Renvoie
    -------
    pandas.DataFrame
        Colonnes ``source``, ``target``, ``value``.
    """
    notices = graphe.notices[graphe.notices["year"].between(premiere_annee, derniere_annee)]
    jointure = (
        graphe.representations[graphe.representations["record_id"].isin(notices["id_biblio"])]
        .merge(graphe.concepts_a[["record_id", "label"]].rename(columns={"label": "A"}), on="record_id")
        .merge(graphe.couples[["record_id", "label"]].rename(columns={"label": "pair"}), on="record_id")
        .merge(graphe.concepts_b[["record_id", "label"]].rename(columns={"label": "B"}), on="record_id")
    )
    triplets = jointure.groupby(["A", "pair", "B"])["work_key"].nunique().rename("weight").reset_index()
    triplets = triplets[triplets["weight"] >= parametres["seuil_poids"]]
    # Les ex aequo à la limite sont départagés par l'ordre des libellés (Neo4j : ordre arbitraire).
    triplets = triplets.sort_values(["weight", "A", "pair", "B"], ascending=[False, True, True, True]).head(
        parametres["liens_max"]
    )
    liens = pd.concat(
        [
            triplets.rename(columns={"A": "source", "pair": "target"})[["source", "target", "weight"]],
            triplets.rename(columns={"pair": "source", "B": "target"})[["source", "target", "weight"]],
        ]
    )
    return (
        liens.groupby(["source", "target"])["weight"]
        .sum()
        .rename("value")
        .reset_index()
        .sort_values("value", ascending=False)
        .reset_index(drop=True)
    )


def chiffres_sankey(liens: pd.DataFrame, parametres: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Part des flux de chaque concept A vers le trio et vers le noyau.

    Paramètres
    ----------
    liens : pandas.DataFrame
    parametres : dict

    Renvoie
    -------
    dict
        Concept A cité vers parts (en %) du trio et du noyau.
    """
    separateur = parametres["separateur_couple"]
    depuis_a = liens[~liens["source"].str.contains(separateur, regex=False)].copy()
    depuis_a["B"] = depuis_a["target"].str.split(separateur).str[1].replace(parametres["fusion_libelles"])
    croise = depuis_a.groupby(["source", "B"])["value"].sum().unstack(fill_value=0)
    total = croise.sum(axis=1)

    def part(groupe: list[str]) -> pd.Series:
        return croise[[c for c in groupe if c in croise]].sum(axis=1) / total * 100

    trio, noyau = part(parametres["trio"]), part(parametres["noyau"])
    return {
        concept: {"trio": round(float(trio[concept]), 1), "noyau": round(float(noyau[concept]), 1)}
        for concept in parametres["concepts_cites"]
        if concept in croise.index
    }


def personnes_par_oeuvre(graphe: GrapheTables) -> pd.Series:
    """Liste triée des personnes signataires de chaque œuvre.

    Paramètres
    ----------
    graphe : GrapheTables

    Renvoie
    -------
    pandas.Series
        Œuvre vers liste de personnes.
    """
    jointure = graphe.signatures.merge(graphe.representations, on="record_id")
    return jointure.groupby("work_key")["person_key"].apply(lambda serie: sorted(set(serie)))


def graphe_coauteurs(personnes: pd.Series, auteurs_max: int) -> nx.Graph:
    """Graphe des co-signatures ; les œuvres de plus de ``auteurs_max`` personnes n'ajoutent pas de liens.

    Le poids d'un lien est le nombre d'œuvres signées ensemble.

    Paramètres
    ----------
    personnes : pandas.Series
        Sortie de ``personnes_par_oeuvre``.
    auteurs_max : int

    Renvoie
    -------
    networkx.Graph
    """
    graphe = nx.Graph()
    graphe.add_nodes_from(sorted(set(itertools.chain.from_iterable(personnes))))
    for signataires in personnes[personnes.apply(len) <= auteurs_max]:
        for premiere, seconde in itertools.combinations(signataires, 2):
            poids = graphe.get_edge_data(premiere, seconde, {"w": 0})["w"] + 1
            graphe.add_edge(premiere, seconde, w=poids)
    return graphe


def chiffres_coauteurs(graphe: GrapheTables, parametres: dict[str, Any]) -> dict[str, Any]:
    """Taille des équipes par période, plus grand réseau, publications uniques.

    Paramètres
    ----------
    graphe : GrapheTables
    parametres : dict
        Section ``[coauteurs]``.

    Renvoie
    -------
    dict
    """
    personnes = personnes_par_oeuvre(graphe)
    effectif = personnes.apply(len)
    annee_oeuvre = (
        graphe.notices.merge(graphe.representations, left_on="id_biblio", right_on="record_id")
        .groupby("work_key")["year"]
        .min()
    )
    oeuvres = pd.DataFrame({"n": effectif}).join(annee_oeuvre)
    oeuvres["periode"] = pd.cut(
        oeuvres["year"].astype(float), parametres["bornes_periodes"], labels=parametres["libelles_periodes"]
    )
    par_periode = oeuvres.groupby("periode", observed=True)["n"]
    reseau = graphe_coauteurs(personnes, parametres["auteurs_max"])
    plus_grand = max(nx.connected_components(reseau), key=len, default=set())
    jointure = graphe.signatures.merge(graphe.representations, on="record_id")
    publications = jointure.groupby("person_key")["work_key"].nunique()
    return {
        "equipes_par_periode": {
            str(cle): round(float(valeur))
            for cle, valeur in par_periode.apply(
                lambda s: (s >= parametres["seuil_equipe"]).mean() * 100
            ).items()
        },
        "signees_seules_par_periode": {
            str(cle): round(float(valeur))
            for cle, valeur in par_periode.apply(lambda s: (s == 1).mean() * 100).items()
        },
        "personnes": reseau.number_of_nodes(),
        "plus_grand_reseau": len(plus_grand),
        "part_plus_grand_reseau": round(len(plus_grand) / max(reseau.number_of_nodes(), 1) * 100),
        "part_une_seule_publication": round(float((publications == 1).mean() * 100)),
    }


def communautes_coauteurs(
    graphe: GrapheTables, parametres: dict[str, Any]
) -> tuple[nx.Graph, list[set[str]], pd.Series]:
    """Communautés de Louvain du plus grand réseau des personnes à deux publications ou plus.

    Paramètres
    ----------
    graphe : GrapheTables
    parametres : dict

    Renvoie
    -------
    reseau : networkx.Graph
        Plus grand réseau connexe.
    communautes : list of set
        Communautés, de la plus grande à la plus petite.
    publications : pandas.Series
        Personne vers nombre d'œuvres.
    """
    personnes = personnes_par_oeuvre(graphe)
    jointure = graphe.signatures.merge(graphe.representations, on="record_id")
    publications = jointure.groupby("person_key")["work_key"].nunique()
    complet = graphe_coauteurs(personnes, parametres["auteurs_max"])
    complet.remove_nodes_from([n for n in list(complet) if not complet.degree(n)])
    actifs = complet.subgraph([n for n in complet if publications.get(n, 0) >= 2]).copy()
    actifs.remove_nodes_from([n for n in list(actifs) if not actifs.degree(n)])
    composantes = sorted(nx.connected_components(actifs), key=len, reverse=True)
    reseau = actifs.subgraph(composantes[0]).copy() if composantes else nx.Graph()
    communautes = sorted(
        (
            nx.community.louvain_communities(reseau, weight="w", seed=parametres["graine_louvain"])
            if reseau.number_of_nodes()
            else []
        ),
        key=len,
        reverse=True,
    )
    return reseau, communautes, publications
