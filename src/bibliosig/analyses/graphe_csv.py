"""Lecture des fichiers d'import du graphe sous forme de tables jointes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class GrapheTables:
    """Nœuds et relations utiles aux analyses.

    Paramètres
    ----------
    notices : pandas.DataFrame
        ``id_biblio``, ``portail``, ``titre``, ``year`` (entier ou manquant).
    portails : pandas.DataFrame
        Relation portail → notice, avec le libellé du portail.
    representations : pandas.DataFrame
        Relation notice → œuvre.
    concepts_a, concepts_b : pandas.DataFrame
        Relations notice → concept, avec code et libellé.
    couples : pandas.DataFrame
        Relation notice → couple, avec libellé.
    signatures : pandas.DataFrame
        Notice, auteur et personne.
    """

    notices: pd.DataFrame
    portails: pd.DataFrame
    representations: pd.DataFrame
    concepts_a: pd.DataFrame
    concepts_b: pd.DataFrame
    couples: pd.DataFrame
    signatures: pd.DataFrame


def lire_graphe(dossier: Path) -> GrapheTables:
    """Lit les CSV d'import du graphe.

    Paramètres
    ----------
    dossier : Path
        Dossier ``neo4j`` produit par l'étape « graphe ».

    Renvoie
    -------
    GrapheTables

    Lève
    ----
    FileNotFoundError
        Si un fichier manque.
    """

    def lire(nom: str) -> pd.DataFrame:
        chemin = dossier / nom
        if not chemin.exists():
            raise FileNotFoundError(f"Fichier du graphe introuvable : {chemin}")
        return pd.read_csv(chemin, dtype=str, keep_default_na=False)

    notices = lire("nodes_records.csv")[["id_biblio", "portail", "titre", "year"]].copy()
    notices["year"] = pd.to_numeric(notices["year"], errors="coerce").astype("Int64")
    portails = lire("rels_has_record.csv").merge(
        lire("nodes_portals.csv").rename(columns={"nodeId": "portal_id", "label": "portal"}),
        on="portal_id",
    )
    concepts_a = lire("rels_matches_a.csv").merge(
        lire("nodes_concepts_a.csv").rename(columns={"code": "concept_code"}), on="concept_code"
    )
    concepts_b = lire("rels_matches_b.csv").merge(
        lire("nodes_concepts_b.csv").rename(columns={"code": "concept_code"}), on="concept_code"
    )
    couples = lire("rels_matched_pair.csv").merge(lire("nodes_pairs.csv"), on="pair_key")
    signatures = lire("rels_authored_by.csv").merge(lire("rels_identified_as.csv"), on="author_key")
    return GrapheTables(
        notices=notices,
        portails=portails,
        representations=lire("rels_represents.csv"),
        concepts_a=concepts_a,
        concepts_b=concepts_b,
        couples=couples,
        signatures=signatures,
    )
