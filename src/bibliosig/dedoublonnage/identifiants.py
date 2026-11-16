"""Première passe : regroupement des notices de même DOI ou de même URI."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from bibliosig.configuration import Configuration
from bibliosig.dedoublonnage.notices import NoticeComparee


class NumeroteurOeuvres:
    """Distribue des identifiants d'œuvre successifs (``wc_000000``, ``wc_000001``…).

    Paramètres
    ----------
    configuration : Configuration
    """

    def __init__(self, configuration: Configuration) -> None:
        parametres = configuration.chaine["dedoublonnage"]
        self.prefixe = parametres["prefixe_oeuvre"]
        self.chiffres = parametres["chiffres_oeuvre"]
        self.prochain = 0

    def suivant(self) -> str:
        """Renvoie un nouvel identifiant d'œuvre.

        Renvoie
        -------
        str
        """
        identifiant = f"{self.prefixe}{self.prochain:0{self.chiffres}d}"
        self.prochain += 1
        return identifiant


def regrouper_par_identifiants(
    notices: dict[str, NoticeComparee], configuration: Configuration
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Regroupe en œuvres les notices de même DOI, puis de même URI.

    Un groupe dont un membre appartient déjà à une œuvre rejoint cette œuvre.

    Paramètres
    ----------
    notices : dict
        id_biblio vers NoticeComparee.
    configuration : Configuration

    Renvoie
    -------
    oeuvre_par_notice : dict
        id_biblio vers identifiant d'œuvre.
    journal_groupes : list of dict
        Un élément par groupe fusionné : clé, type, taille, membres.
    """
    numeroteur = NumeroteurOeuvres(configuration)
    oeuvre_par_notice: dict[str, str] = {}
    journal_groupes: list[dict[str, Any]] = []

    for attribut, type_cle in (("doi_normalise", "DOI"), ("uri_normalisee", "URI/identifiant")):
        groupes: dict[str, list[str]] = defaultdict(list)
        for notice in notices.values():
            cle = getattr(notice, attribut)
            if cle:
                groupes[cle].append(notice.id_biblio)
        for cle, membres in groupes.items():
            if len(membres) < 2:
                continue
            oeuvre = next(
                (oeuvre_par_notice[membre] for membre in membres if membre in oeuvre_par_notice),
                None,
            )
            if oeuvre is None:
                oeuvre = numeroteur.suivant()
            for membre in membres:
                oeuvre_par_notice[membre] = oeuvre
            journal_groupes.append({"cle": cle, "type": type_cle, "n": len(membres), "ids": membres})

    for identifiant in notices:
        if identifiant not in oeuvre_par_notice:
            oeuvre_par_notice[identifiant] = numeroteur.suivant()
    return oeuvre_par_notice, journal_groupes
