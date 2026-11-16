"""La chaîne hors réseau tourne de bout en bout sur les notices fabriquées, en rejeu."""

import json

import pandas as pd
import pytest

from conftest import DONNEES_TEST

pytest.importorskip("rapidfuzz")
pytest.importorskip("sklearn")

from bibliosig.analyses.etape import executer as analyser
from bibliosig.auteurs.etape import executer as regrouper_auteurs
from bibliosig.classification.etape import executer as classer
from bibliosig.dedoublonnage.etape import executer as dedoublonner
from bibliosig.figures.etape import executer as dessiner
from bibliosig.filtrage.etape import executer as filtrer
from bibliosig.fusion.etape import executer as fusionner
from bibliosig.graphe.etape import executer as construire_graphe


def test_chaine_complete(configuration, chemins):
    assert fusionner(configuration, chemins)["notices"] == 11
    bilan_filtres = filtrer(configuration, chemins)
    assert bilan_filtres["negatif"]["rejetees"] == 2
    bilan_dedoublonnage = dedoublonner(configuration, chemins, utiliser_llm=True, rejouer=True)
    assert bilan_dedoublonnage["groupes_par_identifiant"] == 1
    oeuvres = json.loads(chemins.sortie("dedoublonnage_oeuvres").read_text(encoding="utf-8"))
    groupe = next(o for o in oeuvres.values() if "HAL000001" in o["members"])
    assert set(groupe["members"]) == {"HAL000001", "OAL000001", "SUD000001"}

    bilan_classe = classer(configuration, chemins, rejouer=True, dossier_decisions=DONNEES_TEST / "decisions")
    assert bilan_classe["controles_rejeu"]["sans_decision"] == 0
    gardees = pd.read_csv(chemins.sortie("classification_gardees"), dtype=str)
    assert "OAL000003" not in set(gardees["id_biblio"])
    assert set(gardees.loc[gardees["llm_raison"] == "prefiltre", "id_biblio"]) >= {"HAL000001", "PRS000001"}

    bilan_auteurs = regrouper_auteurs(
        configuration, chemins, rejouer=True, dossier_decisions=DONNEES_TEST / "decisions"
    )
    formes = pd.read_csv(chemins.sortie("auteurs_formes"), dtype=str)
    personne = formes.set_index("auteur_raw")["cluster_id"]
    assert personne["Bruno Martin"] == personne["Martin Bruno"]
    assert bilan_auteurs["personnes"] >= 1

    bilan_graphe = construire_graphe(configuration, chemins)
    assert bilan_graphe["noeuds"] > 0 and bilan_graphe["relations"] > 0
    assert (chemins.sortie("dossier_graphe") / "import.cypher").exists()

    chiffres = analyser(configuration, chemins)
    assert chiffres["concepts_et_coauteurs"]["publications_periode"] >= 1
    assert dessiner(configuration, chemins)["figures"]
