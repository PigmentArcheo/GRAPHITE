"""Envoi Zotero hors ligne : conversion, sélection, purge confirmée."""

import argparse

import pytest

from bibliosig.zotero.etape import ConfirmationManquante, notices_a_envoyer, purger
from bibliosig.zotero.notices import element_zotero, prenom_et_nom


def test_element(configuration):
    parametres = configuration.plateformes["zotero"]
    notice = {
        "id_biblio": "HAL000001",
        "portail": "HAL",
        "type": "ARTICLE",
        "titre": "Un <i>SIG</i> fictif",
        "auteurs": "Alice Durand || Marta Sanchez de la Torre",
        "mots_cles": "SIG ; archéologie",
        "AxB": "archéologie × SIG",
        "DOI": "10.9999/fictif.001",
        "date": "2012-01-01",
        "llm_label": "sig",
    }
    element = element_zotero(notice, parametres)
    assert element["itemType"] == "journalArticle" and element["DOI"] == "10.9999/fictif.001"
    assert element["title"] == "Un SIG fictif"
    assert element["extra"].startswith("id_biblio: HAL000001")
    assert {"tag": "AxB:archéologie × SIG"} in element["tags"]
    assert element["creators"][1] == {
        "creatorType": "author",
        "firstName": "Marta Sanchez",
        "lastName": "de la Torre",
    }


def test_nom_avec_virgule():
    assert prenom_et_nom("Durand, Alice", set()) == ("Alice", "Durand")


def test_selection():
    notices = [
        {"id_biblio": "A", "work_cluster_id": "w1", "llm_label": "sig"},
        {"id_biblio": "B", "work_cluster_id": "w1", "llm_label": "sig"},
        {"id_biblio": "C", "work_cluster_id": "w2", "llm_label": "hors_sig"},
    ]
    assert [n["id_biblio"] for n in notices_a_envoyer(notices, par_oeuvre=True, filtre_sig=True)] == ["A"]


def test_purge_exige_la_confirmation(configuration):
    with pytest.raises(ConfirmationManquante):
        purger(None, configuration.plateformes["zotero"], "oui", essai=True)


def test_essai_a_blanc_sans_cle(configuration, chemins, tmp_path, monkeypatch):
    from bibliosig.zotero.etape import executer

    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    fichier = tmp_path / "n.csv"
    fichier.write_text("id_biblio,titre,llm_label\nA,Titre,sig\n", encoding="utf-8")
    arguments = argparse.Namespace(
        cle=None,
        bibliotheque=None,
        type_bibliotheque="group",
        collection=None,
        par_oeuvre=False,
        filtre_sig=True,
        limite=0,
        purge=False,
        confirmer="",
        essai_a_blanc=True,
        fichier=fichier,
    )
    assert executer(configuration, chemins, arguments) == {"a_envoyer": 1}
