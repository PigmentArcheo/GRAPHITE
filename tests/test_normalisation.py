"""Passage au schéma commun et rattachement des paires de mots aux couples de concepts."""

import pandas as pd

from bibliosig.normalisation.etape import (
    attribuer_identifiants,
    normaliser_hal,
    rattacher_aux_couples,
)
from bibliosig.normalisation.schema import auteurs_nom_prenom, etiquette_theses


def test_hal(configuration):
    collecte = pd.DataFrame(
        [
            {
                "halId_s": "hal-1",
                "doiId_s": "",
                "uri_s": "u",
                "authFullName_s": "Alice Durand | Bruno Martin",
                "title_s": "T",
                "abstract_s": "Résumé | Abstract",
                "producedDateY_i": "2012",
                "keyword_s": "a; b",
                "combinaisons_AB": "archéologie × SIG",
                "docType_s": "COUV",
            },
            {
                "halId_s": "",
                "doiId_s": "",
                "uri_s": "",
                "authFullName_s": "",
                "title_s": "",
                "abstract_s": "",
                "producedDateY_i": "",
                "keyword_s": "",
                "combinaisons_AB": "",
                "docType_s": "",
            },
            {
                "halId_s": "hal-3",
                "doiId_s": "",
                "uri_s": "",
                "authFullName_s": "",
                "title_s": "T3",
                "abstract_s": "",
                "producedDateY_i": "",
                "keyword_s": "",
                "combinaisons_AB": "",
                "docType_s": "XYZ",
            },
        ]
    )
    notices = normaliser_hal(collecte, configuration.plateformes["normalisation"]["hal"])
    assert notices["id_biblio"].tolist() == ["HAL000001", "HAL000003"]
    premiere = notices.iloc[0]
    assert premiere["auteurs"] == "Alice Durand || Bruno Martin"
    assert premiere["resume"] == "Résumé" and premiere["mots_cles"] == "a | b"
    assert premiere["type"] == "LIVRE"
    assert notices.iloc[1]["type"] == "AUTRE"


def test_rattachement_sudoc(configuration, tmp_path):
    colonnes = ["PPN", "Type", "Auteurs", "Titre", "Annee", "Revue", "Editeur", "Lieu", "Pages", "ISBN"]
    colonnes += ["ISSN", "Mots-cles", "Resume", "Langue", "Pays", "URL"]
    valeurs = ["012345678", "book", "Durand, Alice ; Martin, Bruno", "Titre fictif", "2012"]
    valeurs += ["", "", "", "", "", "", "SIG", "", "fre", "FR", "https://www.sudoc.fr/012345678"]
    entete = ";".join(f'"{c}"' for c in colonnes) + "\n"
    ligne = ";".join(f'"{v}"' for v in valeurs) + "\n"
    for nom in ("archeologie__x__SIG", "site__x__analyse_spatiale", "archeologie__x__SIG_complet"):
        (tmp_path / f"{nom}.csv").write_text(entete + ligne, encoding="utf-8-sig")
    notices = rattacher_aux_couples("sudoc", tmp_path, configuration)
    assert len(notices) == 1
    notice = notices.iloc[0]
    assert notice["AxB"] == "archéologie × SIG || site × analyse spatiale"
    assert notice["id_portail"] == "12345678"
    assert notice["auteurs"] == "Durand Alice || Martin Bruno" and notice["type"] == "LIVRE"
    assert attribuer_identifiants(notices, "SUD")["id_biblio"].tolist() == ["SUD000001"]


def test_outils_de_schema():
    assert auteurs_nom_prenom("Lefèvre, Émile; Durand, Alice", "; ") == "Lefèvre Émile || Durand Alice"
    assert etiquette_theses("système d'information géographique") == "systeme_dinformation_geographique"
