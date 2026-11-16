"""Étape « analyses » : tableaux des analyses et indicateurs, dans ``<sorties>/analyses``."""

from __future__ import annotations

import logging
from typing import Any

from bibliosig.analyses.publications import (
    co_occurrences_concepts,
    notices_par_portail_et_annee,
    oeuvres_par_annee,
    oeuvres_par_concept_et_annee,
)
from bibliosig.analyses.concepts_et_coauteurs import (
    chiffres_coauteurs,
    chiffres_mots_cles,
    chiffres_reseau,
    chiffres_sankey,
    communautes_coauteurs,
    liens_sankey,
    parts_mots_cles,
)
from bibliosig.analyses.graphe_csv import lire_graphe
from bibliosig.analyses.mots_titres import co_occurrences_titres
from bibliosig.communs.tableaux import ecrire_csv, ecrire_json
from bibliosig.configuration import Chemins, Configuration

journal = logging.getLogger(__name__)


def executer(
    configuration: Configuration, chemins: Chemins, expressions_protegees: bool = False
) -> dict[str, Any]:
    """Calcule les tableaux des analyses et les indicateurs résumés.

    Paramètres
    ----------
    configuration : Configuration
    chemins : Chemins
    expressions_protegees : bool
        Mots des titres : ajoute les expressions protégées (synonymes de SIG et d'analyse spatiale).

    Renvoie
    -------
    dict
        Indicateurs résumés, aussi écrits dans ``chiffres.json``.
    """
    parametres = configuration.analyses
    premiere = parametres["periode"]["premiere_annee"]
    derniere = parametres["periode"]["derniere_annee"]
    annees = range(premiere, derniere + 1)
    graphe = lire_graphe(chemins.sortie("dossier_graphe"))
    dossier = chemins.sorties / "analyses"

    notices_portail_annee = notices_par_portail_et_annee(graphe, premiere, derniere)
    oeuvres_concept_annee = oeuvres_par_concept_et_annee(graphe, premiere)
    co_occurrences = co_occurrences_concepts(graphe)
    publications = oeuvres_par_annee(graphe, premiere, derniere)
    sankey = liens_sankey(graphe, parametres["sankey"], premiere, derniere)
    mots_titres = co_occurrences_titres(
        graphe, parametres["mots_titres"], premiere, derniere, expressions_protegees
    )
    parts = parts_mots_cles(oeuvres_concept_annee, parametres["mots_cles"], annees)
    for nom, tableau in (
        ("notices_portail_annee", notices_portail_annee),
        ("oeuvres_concept_annee", oeuvres_concept_annee),
        ("co_occurrences_concepts", co_occurrences),
        ("publications_par_annee", publications),
        ("sankey_concepts", sankey),
        ("mots_titres_co_occurrences", mots_titres),
    ):
        ecrire_csv(tableau, dossier / f"{nom}.csv")
    ecrire_csv(parts.reset_index(), dossier / "parts_mots_cles.csv")

    reseau, communautes, nombre_publications = communautes_coauteurs(
        graphe, parametres["coauteurs"]
    )
    communaute_par_personne = {
        personne: rang for rang, communaute in enumerate(communautes) for personne in communaute
    }
    ecrire_json(
        {
            "noeuds": [
                {
                    "id": personne,
                    "communaute": communaute_par_personne[personne],
                    "publications": int(nombre_publications.get(personne, 0)),
                }
                for personne in sorted(reseau)
            ],
            "liens": [
                [premiere_personne, seconde, int(donnees["w"])]
                for premiere_personne, seconde, donnees in reseau.edges(data=True)
            ],
        },
        dossier / "coauteurs_communautes.json",
    )

    notices_annuelles = notices_portail_annee.groupby("year")["nb_records"].sum()
    publications_annuelles = publications.set_index("year")["nbWorks"]
    citees = parametres["publications"]["annees_citees"]
    chiffres = {
        "publications": {
            "notices_par_annee_citee": {str(a): int(notices_annuelles.get(a, 0)) for a in citees},
            "notices_periode": int(notices_annuelles.sum()),
            "co_occurrences_principales": [int(p) for p in co_occurrences["weight"].head(5)],
        },
        "concepts_et_coauteurs": {
            "publications_periode": int(publications_annuelles.sum()),
            "publications_moyenne": round(float(publications_annuelles.mean())),
            "publications_par_annee_citee": {str(a): int(publications_annuelles.get(a, 0)) for a in citees},
            "mots_cles": chiffres_mots_cles(parts, parametres["mots_cles"]),
            "reseau": chiffres_reseau(co_occurrences, parametres["reseau"]),
            "sankey": chiffres_sankey(sankey, parametres["sankey"]),
            "coauteurs": chiffres_coauteurs(graphe, parametres["coauteurs"]),
            "communautes": [len(communaute) for communaute in communautes[:12]],
            "liens_mots_titres": len(mots_titres),
        },
    }
    ecrire_json(chiffres, dossier / "chiffres.json")
    journal.info("Analyses écrites dans %s", dossier)
    return chiffres
