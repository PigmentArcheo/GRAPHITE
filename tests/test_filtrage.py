"""Filtres thématiques et pré-filtre SIG."""

import pandas as pd

from bibliosig.classification.decisions import Decision, motif_prefiltre, prefiltrer
from bibliosig.classification.etape import destinations
from bibliosig.communs.tableaux import texte_avec_nan
from bibliosig.filtrage.etape import masque_conservation_positive, masque_rejet_negatif


def notices(*lignes):
    return pd.DataFrame(lignes, columns=["titre", "resume", "mots_cles", "AxB"])


def test_filtre_negatif_protege_le_signal_archeologique(configuration):
    tableau = notices(
        ["Protein folding", "", "", "site × SIG"],
        ["Protein residues in ancient pottery", "archéologie", "", "site × SIG"],
    )
    assert masque_rejet_negatif(tableau, configuration).tolist() == [True, False]


def test_filtre_positif_par_concept_strict(configuration):
    tableau = notices(
        ["Titre sans vocabulaire", "", "", "fouille × SIG"], ["Titre neutre", "", "", "site × SIG"]
    )
    assert masque_conservation_positive(tableau, configuration).tolist() == [True, False]


def test_champ_vide_rendu_en_nan():
    assert texte_avec_nan("") == "nan"
    assert texte_avec_nan("texte") == "texte"


def test_prefiltre_et_seuils(configuration):
    motif = motif_prefiltre(configuration)
    notice = pd.Series({"titre": "Usage de QGIS en prospection", "resume": "", "mots_cles": "", "AxB": ""})
    assert prefiltrer(notice, motif, configuration) == Decision("sig", 0.95, "prefiltre")
    neutre = pd.Series({"titre": "Céramique", "resume": "", "mots_cles": "", "AxB": "fouille × LiDAR"})
    assert prefiltrer(neutre, motif, configuration) is None
    assert destinations(Decision("sig", 0.65, "x"), configuration) == set()
    assert destinations(Decision("hors_sig", 0.5, "x"), configuration) == {
        "classification_rejetees",
        "classification_a_relire",
    }
    assert destinations(Decision("sig", 0.7, "x"), configuration) == {"classification_gardees"}
