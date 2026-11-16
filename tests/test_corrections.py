"""Les corrections manuelles se déduisent et se rejouent à l'identique."""

import pandas as pd

from bibliosig.normalisation.corrections import appliquer_corrections, deduire_corrections


def tableau(lignes):
    return pd.DataFrame(lignes, columns=["id_biblio", "titre", "type"])


def test_aller_retour_ajout_retrait_deplacement_modification():
    avant = tableau([["A", "a", "x"], ["B", "b", "x"], ["C", "c", "x"], ["D", "d", "x"]])
    apres = tableau([["D", "d", "x"], ["A", "a", "y"], ["E", "e", "z"], ["C", "c", "x"]])
    corrections = deduire_corrections(avant, apres, "f.csv", ["id_biblio"])
    assert set(corrections["operation"]) == {"retirer", "ajouter", "deplacer", "modifier"}
    corrige, modifications = appliquer_corrections(avant, corrections, ["id_biblio"])
    assert corrige.values.tolist() == apres.values.tolist()
    assert modifications > 0
    deuxieme, aucune = appliquer_corrections(corrige, corrections, ["id_biblio"])
    assert deuxieme.values.tolist() == apres.values.tolist() and aucune == 0


def test_cle_composee():
    avant = pd.DataFrame([["Durand Alice", "fallback", "1"]], columns=["auteur_raw", "origine", "cluster_id"])
    apres = pd.DataFrame(
        [["Durand Alice", "fallback", "2"], ["Durand Alice", "alias", "2"]],
        columns=["auteur_raw", "origine", "cluster_id"],
    )
    corrections = deduire_corrections(avant, apres, "auteurs_clusters.csv", ["auteur_raw", "origine"])
    corrige, _ = appliquer_corrections(avant, corrections, ["auteur_raw", "origine"])
    assert corrige.values.tolist() == apres.values.tolist()
