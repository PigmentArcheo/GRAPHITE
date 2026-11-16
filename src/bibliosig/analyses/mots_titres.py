"""Co-occurrences des mots des titres par année, équivalent de la requête Neo4j."""

from __future__ import annotations

import itertools
from collections import Counter
from typing import Any

import pandas as pd

from bibliosig.analyses.graphe_csv import GrapheTables


class DecoupeurTitres:
    """Découpe un titre en mots normalisés, selon une suite fixe d'étapes (accents, ponctuation, expressions, pluriels).

    Paramètres
    ----------
    parametres : dict
        Section ``[mots_titres]``.
    expressions_protegees : bool
        Ajoute les synonymes de SIG et d'analyse spatiale (pluriels, autres langues) avant les expressions des méthodes.
    """

    def __init__(self, parametres: dict[str, Any], expressions_protegees: bool) -> None:
        self.parametres = parametres
        self.remplacements: list[tuple[str, str]] = [tuple(paire) for paire in parametres["accents"]]
        self.remplacements += [(signe, " ") for signe in parametres["ponctuation"]]
        self.remplacements += [(signe, " ") for signe in parametres["apostrophes"]]
        cles = ["expressions_anglaises", "expressions_periodes", "expressions_periodes_lieux"]
        if expressions_protegees:
            cles.append("expressions_sig_analyse_spatiale")
        cles.append("expressions_methodes")
        for cle in cles:
            self.remplacements += [tuple(paire) for paire in parametres[cle]]
        self.proteges = set(parametres["mots_proteges"])
        self.normalisation = {}
        for forme, mots in parametres["normalisations"].items():
            for mot in mots:
                self.normalisation.setdefault(mot, forme)
        self.vides = set(parametres["vides"]["mots"])

    def mots(self, titre: str) -> list[str]:
        """Mots retenus d'un titre.

        Paramètres
        ----------
        titre : str

        Renvoie
        -------
        list of str
        """
        texte = titre.lower()
        for motif, remplacement in self.remplacements:
            texte = texte.replace(motif, remplacement)
        retenus = []
        for morceau in texte.split(" "):
            mot = morceau.strip()
            if len(mot) < self.parametres["longueur_min_mot"]:
                continue
            if (
                mot not in self.proteges
                and "_" not in mot
                and mot.endswith("s")
                and len(mot) >= self.parametres["longueur_min_pluriel"]
            ):
                mot = mot[:-1]
            mot = self.normalisation.get(mot, mot)
            if mot not in self.vides:
                retenus.append(mot)
        return retenus


def co_occurrences_titres(
    graphe: GrapheTables,
    parametres: dict[str, Any],
    premiere_annee: int,
    derniere_annee: int,
    expressions_protegees: bool = False,
) -> pd.DataFrame:
    """Paires de mots présents ensemble dans les titres d'une œuvre, par année.

    Paramètres
    ----------
    graphe : GrapheTables
    parametres : dict
    premiere_annee, derniere_annee : int
    expressions_protegees : bool

    Renvoie
    -------
    pandas.DataFrame
        Colonnes ``year``, ``source``, ``target``, ``weight`` (œuvres distinctes).
    """
    decoupeur = DecoupeurTitres(parametres, expressions_protegees)
    notices = graphe.notices[(graphe.notices["titre"] != "") & graphe.notices["year"].notna()]
    jointure = notices.merge(graphe.representations, left_on="id_biblio", right_on="record_id")
    mots_par_oeuvre: dict[tuple[int, str], set[str]] = {}
    for annee, oeuvre, titre in zip(jointure["year"], jointure["work_key"], jointure["titre"], strict=True):
        mots_par_oeuvre.setdefault((int(annee), oeuvre), set()).update(decoupeur.mots(titre))
    comptes: Counter[tuple[int, str, str]] = Counter()
    for (annee, _oeuvre), mots in mots_par_oeuvre.items():
        for premier, second in itertools.combinations(sorted(mots), 2):
            comptes[(annee, premier, second)] += 1
    lignes = [
        {"year": annee, "source": premier, "target": second, "weight": poids}
        for (annee, premier, second), poids in comptes.items()
        if poids >= parametres["poids_min"] and premiere_annee <= annee <= derniere_annee
    ]
    resultat = pd.DataFrame(lignes, columns=["year", "source", "target", "weight"])
    return resultat.sort_values(["year", "weight"], ascending=[True, False]).reset_index(drop=True)
