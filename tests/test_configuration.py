"""La configuration décrit les concepts et les paramètres de la chaîne."""

from bibliosig.collecte.couples import concept_par_mot, couples_de_concepts, paires_de_mots


def test_concepts_des_blocs(configuration):
    bloc_a, bloc_b = configuration.concepts["bloc_a"], configuration.concepts["bloc_b"]
    assert len(bloc_a) == 10 and len(bloc_b) == 10
    assert sum(len(c["termes"]) for c in bloc_a) == 37
    assert sum(len(c["termes"]) for c in bloc_b) == 24
    for concept in bloc_a + bloc_b:
        assert set(concept["termes_fr"]) | set(concept["termes_en"]) == set(concept["termes"])


def test_couples_par_plateforme(configuration):
    assert len(couples_de_concepts(configuration, "hal")) == 100
    persee = couples_de_concepts(configuration, "persee")
    assert len(persee) == 90
    assert "cartographie/mapping/webSIG" in {b.libelle for _, b in persee}


def test_paires_de_mots_et_rattachement(configuration):
    for plateforme in ("sudoc", "theses", "frantiq"):
        assert len(paires_de_mots(configuration, plateforme)) == 266
    concepts = concept_par_mot(configuration, "mots_sans_accents")
    mots = configuration.plateformes["mots_terme_a_terme"]
    assert all(mot in concepts for mot in mots["sans_accents_a"] + mots["sans_accents_b"])
    assert concepts["geohistoire"] == "archéogéographie"
    assert concepts["apprentissage profond"] == "deep learning"
    theses = concept_par_mot(configuration, "mots_theses")
    assert all(mot in theses for mot in mots["theses_a"] + mots["theses_b"])


def test_seuils_et_motifs(configuration):
    assert configuration.chaine["classification"]["seuil_confiance"] == 0.7
    assert configuration.chaine["classification"]["seuil_relecture"] == 0.6
    assert len(configuration.filtres["filtre_negatif"]["motifs_hors_sujet"]) == 71
    assert len(configuration.filtres["filtre_positif"]["motifs_archeologiques"]) == 138
    assert configuration.analyses["coauteurs"]["auteurs_max"] == 30
    assert configuration.chaine["llm"]["modele"] == "mistral"


def test_instructions_cypher():
    from importlib import resources

    from bibliosig.graphe.import_neo4j import instructions

    script = resources.files("bibliosig.graphe").joinpath("import.cypher").read_text(encoding="utf-8")
    liste = instructions(script)
    assert liste[0].startswith("CREATE CONSTRAINT portal_id")
    assert not any(ligne.lstrip().startswith("//") for i in liste for ligne in i.splitlines())
    assert sum("LOAD CSV" in instruction for instruction in liste) == 17
