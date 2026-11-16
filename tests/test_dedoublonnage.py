"""Règles du dédoublonnage des notices et des auteurs."""

import pandas as pd
import pytest

pytest.importorskip("rapidfuzz")

from bibliosig.auteurs.noms import cle_famille, cle_permutation, normaliser_forme  # noqa: E402
from bibliosig.auteurs.regroupements import regrouper_precocement  # noqa: E402
from bibliosig.dedoublonnage.identifiants import regrouper_par_identifiants  # noqa: E402
from bibliosig.dedoublonnage.notices import preparer_notices  # noqa: E402
from bibliosig.dedoublonnage.similarite import est_paire_compagnon, regrouper_par_similarite  # noqa: E402

COLONNES = ["id_biblio", "portail", "DOI", "uri", "auteurs", "titre", "date"]


def preparer(configuration, lignes):
    tableau = pd.DataFrame(lignes, columns=COLONNES)
    return preparer_notices(tableau, configuration)


def test_meme_doi_meme_oeuvre(configuration):
    notices = preparer(
        configuration,
        [
            ["A1", "HAL", "10.1/X", "", "", "Titre un", "2010"],
            ["A2", "OPENALEX", "https://doi.org/10.1/x", "", "", "Autre titre", "2010"],
            ["A3", "HAL", "", "", "", "Encore un autre", "2010"],
        ],
    )
    oeuvres, groupes = regrouper_par_identifiants(notices, configuration)
    assert oeuvres["A1"] == oeuvres["A2"] != oeuvres["A3"]
    assert len(groupes) == 1


def test_doi_absent_fusion_seulement_au_dessus_du_seuil(configuration):
    titre = "Une étude fictive de la répartition des habitats protohistoriques en plaine"
    notices = preparer(
        configuration,
        [
            ["B1", "HAL", "10.1/a", "", "", titre, "2010"],
            ["B2", "FRANTIQ", "", "", "", titre + " méthode", "2010"],
            ["B3", "SUDOC", "", "", "", titre, "2011"],
        ]
        + [[f"Z{i}", "HAL", "", "", "", f"Remplissage {i} sans rapport aucun", "2000"] for i in range(5)],
    )
    oeuvres, _ = regrouper_par_identifiants(notices, configuration)
    journal = regrouper_par_similarite(notices, oeuvres, configuration, 0.85)
    assert oeuvres["B1"] == oeuvres["B3"]
    assert oeuvres["B2"] != oeuvres["B1"]
    assert any(e["mode"] == "dois_différents" for e in journal)


def test_paire_compagnon(configuration):
    assert est_paire_compagnon(
        "Fouilles de Valombre", "Fouilles de Valombre : supplementary data", configuration
    )
    assert not est_paire_compagnon("Fouilles de Valombre", "Fouilles de Valombre", configuration)


def test_normalisation_des_noms(configuration):
    assert normaliser_forme("Émile  Lefèvre") == "emile lefevre"
    assert cle_permutation("Martin Bruno") == cle_permutation("Bruno Martin")
    particules = configuration.chaine["auteurs"]["particules"]
    assert cle_famille("marta de la torre", particules) == "marta|torre"
    assert regrouper_precocement(["Bruno Martin", "Martin Bruno", "Chloé Petit"], 0.95) == [
        ["Bruno Martin", "Martin Bruno"],
        ["Chloé Petit"],
    ]
