"""Collecte hors ligne : requêtes construites, réponses enregistrées, aucune clé dans les journaux."""

import logging

import pytest
import requests
from defusedxml import DefusedXmlException

from bibliosig.collecte import frantiq, hal, openalex, sudoc, theses
from bibliosig.collecte.couples import couples_de_concepts
from bibliosig.collecte.http import masquer_secrets, signature
from bibliosig.collecte.marc import analyser_xml, champ, extraire
from bibliosig.collecte.registre import RegistreNotices
from conftest import FausseReponse, FausseSession, lire_reponse


def test_signature_sans_adresse(configuration):
    texte = signature(configuration)
    assert texte.startswith("bibliosig/") and "@" not in texte and "Mozilla" not in texte


def test_requete_hal_un_ou_par_concept(configuration):
    concept_a, concept_b = couples_de_concepts(configuration, "hal")[0]
    requete = hal.requete_couple(concept_a, concept_b, configuration.plateformes["hal"])
    assert requete.count(" AND ") == 1
    assert 'title_t:"archaeology"' in requete and 'abstract_t:"GIS"' in requete


def test_pages_hal(configuration):
    session = FausseSession([FausseReponse(lire_reponse("hal_page.json"))])
    total, documents = hal.interroger(session, "q", configuration.plateformes["hal"])
    assert total == 2 and len(documents) == 2
    assert session.appels[0]["params"]["fq"].startswith("docType_s:(")
    plat = hal.aplatir(documents[0], configuration.plateformes["hal"]["champs_renvoyes"])
    assert plat["authFullName_s"] == "Alice Durand | Bruno Martin"


def test_filtre_openalex(configuration):
    concept_a, concept_b = couples_de_concepts(configuration, "openalex")[0]
    filtre = openalex.filtre_couple(concept_a, concept_b, configuration.plateformes["openalex"])
    assert filtre.count("title_and_abstract.search:") == 2
    assert "institutions.country_code:fr" in filtre
    assert '"système d\'information géographique"' in filtre


def test_aplatir_openalex(configuration):
    import json

    oeuvre = json.loads(lire_reponse("openalex_page.json"))["results"][0]
    plat = openalex.aplatir(oeuvre)
    assert plat["doi"] == "10.9999/fictif.002"
    assert plat["abstract"] == "Relevés LiDAR archéologiques"
    assert plat["institutions"] == "Laboratoire fictif (fr)"


def test_cle_openalex_masquee(configuration, caplog):
    parametres = {
        **configuration.plateformes["openalex"],
        "pause_erreur_reseau_secondes": 0,
        "tentatives_max": 1,
    }

    class SessionEnErreur:
        def get(self, url, params=None, **options):
            raise requests.ConnectionError(f"echec {url}?api_key={params['api_key']}&filter=x")

    with caplog.at_level(logging.DEBUG):
        assert openalex.appeler(SessionEnErreur(), {"api_key": "CLE-FICTIVE-123"}, parametres) is None
    assert "CLE-FICTIVE-123" not in caplog.text
    assert "api_key=***" in caplog.text
    assert masquer_secrets("https://x/?api_key=abc&b=1") == "https://x/?api_key=***&b=1"


def test_registre_garde_tous_les_couples(tmp_path):
    registre = RegistreNotices("id")
    registre.enregistrer("n1", {"id": "n1", "titre": "t"}, "archéologie", "SIG")
    registre.enregistrer("n1", {"id": "n1", "titre": "t"}, "fouille", "SIG")
    registre.enregistrer("n1", {"id": "n1", "titre": "t"}, "fouille", "SIG")
    assert registre.ecrire(tmp_path / "d.csv", ["id", "titre"]) == 1
    assert "archéologie × SIG || fouille × SIG" in (tmp_path / "d.csv").read_text(encoding="utf-8-sig")


def test_sudoc_unimarc(configuration):
    assert (
        sudoc.requete("analyse spatiale", "sig")
        == "tou%3D%22analyse%20spatiale%22 and tou%3Dsig and (lan%3Dfre or pay%3Dfr)"
    )
    session = FausseSession([FausseReponse(lire_reponse("sudoc_page.xml"))])
    notices, total = sudoc.interroger(session, "archeologie", "sig", configuration.plateformes["sudoc"])
    assert total == 1
    assert notices[0]["title"] == "Un SIG pour la fouille : site fictif de Valombre"
    assert notices[0]["authors"] == ["Durand, Alice"]
    assert notices[0]["url"] == "https://www.sudoc.fr/012345678"


def test_xml_piege_refuse():
    with pytest.raises(DefusedXmlException):
        analyser_xml(lire_reponse("xml_piege.xml"))


def test_frantiq_recherche_et_notice(configuration):
    numeros, total = frantiq.lire_page_resultats(lire_reponse("frantiq_recherche.html").decode("utf-8"))
    assert numeros == ["900001", "900002"] and total == 2
    session = FausseSession([FausseReponse(lire_reponse("frantiq_notice.xml"))])
    notice = frantiq.notice_marc(session, "900001", configuration.plateformes["frantiq"])
    assert notice["title"] == "Atlas archéologique de la cité fictive"
    assert notice["authors"] == ["Hubert, Gérard"]
    assert notice["url"].endswith("biblionumber=900001")


def test_theses_lecture(configuration):
    import json

    trouvees, total = theses.lire_reponse(
        json.loads(lire_reponse("theses_page.json")), configuration.plateformes["theses"]
    )
    assert total == 1
    these = trouvees[0]
    assert these["auteur"] == "Lefèvre, Émile" and these["annee"] == "2019"
    assert these["mots_cles"] == "SIG; Néolithique"
    assert these["url"] == "https://theses.fr/2019FICT0001"


def test_lecture_unimarc_generique():
    racine = analyser_xml(lire_reponse("sudoc_page.xml"))
    assert champ(racine, "001") == ["012345678"]
    assert extraire(racine, champ, sudoc.REGLES_UNIMARC, "012345678")["year"] == "2012"
