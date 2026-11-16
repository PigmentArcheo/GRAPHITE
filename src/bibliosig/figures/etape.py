"""Étape « figures » : une image PNG par analyse, dans ``<sorties>/figures``."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd

from bibliosig.communs.tableaux import lire_json
from bibliosig.configuration import Chemins, Configuration
from bibliosig.figures.parametres_coauteurs import lire_parametres_coauteurs

journal = logging.getLogger(__name__)


def enregistrer(figure: plt.Figure, chemin: Path) -> None:
    """Enregistre une figure et libère sa mémoire.

    Paramètres
    ----------
    figure : matplotlib.figure.Figure
    chemin : Path
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(chemin, bbox_inches="tight", dpi=150)
    plt.close(figure)
    journal.info("Figure : %s", chemin.name)


def donnees_vides(tableau: pd.DataFrame, sortie: Path) -> bool:
    """Signale qu'une figure n'est pas dessinée faute de données.

    Paramètres
    ----------
    tableau : pandas.DataFrame
    sortie : Path

    Renvoie
    -------
    bool
    """
    if tableau.empty:
        journal.warning("Pas de données pour %s : figure non dessinée", sortie.name)
        return True
    return False


def figure_publications(analyses: Path, sortie: Path) -> None:
    """Notices par plateforme et par année, en barres empilées.

    Paramètres
    ----------
    analyses : Path
    sortie : Path
    """
    tableau = pd.read_csv(analyses / "notices_portail_annee.csv")
    if donnees_vides(tableau, sortie):
        return
    croise = tableau.pivot_table(index="year", columns="portal", values="nb_records", fill_value=0)
    figure, axe = plt.subplots(figsize=(10, 5))
    croise.plot.bar(stacked=True, ax=axe, width=0.85)
    axe.legend(title="Plateforme")
    axe.set_xlabel("Année")
    axe.set_ylabel("Notices")
    axe.set_title("Publications par année et par plateforme")
    enregistrer(figure, sortie)


def figure_parts_mots_cles(analyses: Path, sortie: Path) -> None:
    """Part relative des mots-clés du bloc B, en aires empilées.

    Paramètres
    ----------
    analyses : Path
    sortie : Path
    """
    parts = pd.read_csv(analyses / "parts_mots_cles.csv").set_index("year")
    if donnees_vides(parts, sortie):
        return
    figure, axe = plt.subplots(figsize=(10, 5))
    parts.plot.area(ax=axe, linewidth=0)
    axe.set_xlabel("Année")
    axe.set_ylabel("Part des œuvres (%)")
    axe.set_title("Part relative des mots-clés du bloc B")
    axe.legend(loc="center left", bbox_to_anchor=(1, 0.5))
    enregistrer(figure, sortie)


def figure_reseau_concepts(analyses: Path, sortie: Path, seuil: int) -> None:
    """Réseau biparti des concepts A et B, épaisseur selon les œuvres communes.

    Paramètres
    ----------
    analyses : Path
    sortie : Path
    seuil : int
        Poids minimal d'un lien dessiné.
    """
    tableau = pd.read_csv(analyses / "co_occurrences_concepts.csv")
    tableau = tableau[tableau["weight"] >= seuil]
    if donnees_vides(tableau, sortie):
        return
    reseau = nx.Graph()
    for ligne in tableau.itertuples(index=False):
        reseau.add_edge(f"A : {ligne.labelA}", f"B : {ligne.labelB}", poids=ligne.weight)
    positions = nx.spring_layout(reseau, weight="poids", seed=1)
    poids_max = max((d["poids"] for _, _, d in reseau.edges(data=True)), default=1)
    figure, axe = plt.subplots(figsize=(10, 8))
    nx.draw_networkx_edges(
        reseau,
        positions,
        ax=axe,
        alpha=0.4,
        width=[4 * d["poids"] / poids_max for _, _, d in reseau.edges(data=True)],
    )
    couleurs = ["#41A8BF" if noeud.startswith("A") else "#E99A5C" for noeud in reseau]
    nx.draw_networkx_nodes(reseau, positions, ax=axe, node_color=couleurs, node_size=120)
    nx.draw_networkx_labels(reseau, positions, ax=axe, font_size=7)
    axe.set_title("Co-occurrences des concepts A et B (œuvres distinctes)")
    axe.axis("off")
    enregistrer(figure, sortie)


def figure_sankey(analyses: Path, sortie: Path) -> None:
    """Flux concept A → couple → concept B, en barres horizontales par concept A.

    Paramètres
    ----------
    analyses : Path
    sortie : Path
    """
    liens = pd.read_csv(analyses / "sankey_concepts.csv")
    depuis_a = liens[~liens["source"].str.contains(" × ", regex=False)].copy()
    if donnees_vides(depuis_a, sortie):
        return
    depuis_a["B"] = depuis_a["target"].str.split(" × ").str[1]
    croise = depuis_a.pivot_table(index="source", columns="B", values="value", aggfunc="sum", fill_value=0)
    croise = croise.div(croise.sum(axis=1), axis=0) * 100
    figure, axe = plt.subplots(figsize=(10, 5))
    croise.plot.barh(stacked=True, ax=axe)
    axe.set_xlabel("Part des flux (%)")
    axe.set_ylabel("Concept A")
    axe.set_title("Flux des concepts A vers les concepts B")
    axe.legend(loc="center left", bbox_to_anchor=(1, 0.5), fontsize=7)
    enregistrer(figure, sortie)


def noms_personnes(dossier_graphe: Path, corrections: dict[str, str]) -> dict[str, str]:
    """Nom affiché de chaque personne du graphe, après corrections d'affichage.

    Paramètres
    ----------
    dossier_graphe : Path
    corrections : dict

    Renvoie
    -------
    dict
        Identifiant de personne vers nom affiché.
    """
    personnes = pd.read_csv(dossier_graphe / "nodes_persons.csv", dtype=str, keep_default_na=False)
    return {
        cle: corrections.get(nom, nom)
        for cle, nom in zip(personnes["person_key"], personnes["canonical_name"], strict=True)
    }


def dessiner_reseau(
    reseau: nx.Graph,
    positions: dict[str, Any],
    noms: dict[str, str],
    etiquettes: set[str],
    titre: str,
    sortie: Path,
) -> None:
    """Dessine un réseau de personnes coloré par communauté.

    Paramètres
    ----------
    reseau : networkx.Graph
    positions : dict
    noms : dict
    etiquettes : set of str
        Noms affichés à écrire sur la figure.
    titre : str
    sortie : Path
    """
    palette = plt.get_cmap("tab20")
    figure, axe = plt.subplots(figsize=(10, 10))
    nx.draw_networkx_edges(reseau, positions, ax=axe, alpha=0.08, width=0.4)
    nx.draw_networkx_nodes(
        reseau,
        positions,
        ax=axe,
        node_color=[palette(reseau.nodes[n]["communaute"] % 20) for n in reseau],
        node_size=[4 + 2 * reseau.nodes[n]["publications"] for n in reseau],
    )
    for cle in reseau:
        if noms.get(cle) in etiquettes:
            axe.text(*positions[cle], noms[cle], fontsize=7)
    axe.set_title(titre)
    axe.axis("off")
    enregistrer(figure, sortie)


def figure_coauteurs(analyses: Path, dossier_graphe: Path, sortie: Path, parametres: dict[str, Any]) -> None:
    """Réseau des co-auteurs coloré par communauté de Louvain, et vues de détail.

    Paramètres
    ----------
    analyses : Path
    dossier_graphe : Path
    sortie : Path
        Image du réseau complet ; les vues de détail sont écrites à côté.
    parametres : dict
        Paramètres nominatifs lus hors du dépôt ; vide si absents.
    """
    donnees = lire_json(analyses / "coauteurs_communautes.json")
    if donnees_vides(pd.DataFrame(donnees["noeuds"]), sortie):
        return
    reseau = nx.Graph()
    for noeud in donnees["noeuds"]:
        reseau.add_node(noeud["id"], communaute=noeud["communaute"], publications=noeud["publications"])
    reseau.add_weighted_edges_from(donnees["liens"], weight="w")
    noms = noms_personnes(dossier_graphe, parametres.get("corrections_noms", {}))
    cle_par_nom = {nom: cle for cle, nom in noms.items() if cle in reseau}
    fixees = {
        cle_par_nom[nom]: tuple(position)
        for nom, position in parametres.get("positions_fixees", {}).items()
        if nom in cle_par_nom
    }
    positions = nx.spring_layout(reseau, weight="w", seed=2, pos=fixees or None, fixed=list(fixees) or None)
    etiquettes = set(parametres.get("etiquettes", []))
    dessiner_reseau(
        reseau, positions, noms, etiquettes, "Réseau des co-auteurs (communautés de Louvain)", sortie
    )
    for groupe, membres in parametres.get("groupes_zoom", {}).items():
        cles = [cle_par_nom[nom] for nom in membres if nom in cle_par_nom]
        if not cles:
            continue
        sous_reseau = reseau.subgraph(cles)
        sous_positions = nx.spring_layout(sous_reseau, weight="w", seed=1)
        dessiner_reseau(
            sous_reseau,
            sous_positions,
            noms,
            set(membres),
            f"Vue de détail : {groupe}",
            sortie.with_name(f"{sortie.stem}_zoom_{groupe}.png"),
        )


def figure_mots_titres(analyses: Path, sortie: Path) -> None:
    """Nombre de liens entre mots des titres, par année.

    Paramètres
    ----------
    analyses : Path
    sortie : Path
    """
    liens = pd.read_csv(analyses / "mots_titres_co_occurrences.csv")
    if donnees_vides(liens, sortie):
        return
    figure, axe = plt.subplots(figsize=(10, 4))
    liens.groupby("year").size().plot.bar(ax=axe)
    axe.set_xlabel("Année")
    axe.set_ylabel("Paires de mots (au moins 3 œuvres)")
    axe.set_title("Co-occurrences des mots des titres par année")
    enregistrer(figure, sortie)


def executer(configuration: Configuration, chemins: Chemins) -> dict[str, Any]:
    """Dessine les figures à partir des données de l'étape « analyses ».

    Paramètres
    ----------
    configuration : Configuration
    chemins : Chemins

    Renvoie
    -------
    dict
        Liste des figures écrites.
    """
    plt.switch_backend("Agg")
    analyses = chemins.sorties / "analyses"
    dossier = chemins.sorties / "figures"
    seuil = configuration.analyses["publications"]["seuil_lien_co_occurrence"]
    figure_publications(analyses, dossier / "publications.png")
    figure_parts_mots_cles(analyses, dossier / "mots_cles.png")
    figure_reseau_concepts(analyses, dossier / "reseau_concepts.png", seuil)
    figure_sankey(analyses, dossier / "sankey.png")
    figure_coauteurs(
        analyses,
        chemins.sortie("dossier_graphe"),
        dossier / "coauteurs.png",
        lire_parametres_coauteurs(chemins.donnees),
    )
    figure_mots_titres(analyses, dossier / "mots_titres.png")
    return {"figures": sorted(chemin.name for chemin in dossier.glob("*.png"))}
