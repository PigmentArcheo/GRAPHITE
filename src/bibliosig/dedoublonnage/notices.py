"""Champs de travail calculés pour comparer les notices."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from bibliosig.communs.normalisation import (
    extraire_annee,
    normaliser_doi,
    normaliser_liste_auteurs,
    normaliser_titre,
    normaliser_uri,
)
from bibliosig.configuration import Configuration


@dataclass(frozen=True)
class NoticeComparee:
    """Forme normalisée d'une notice pour le dédoublonnage.

    Paramètres
    ----------
    id_biblio, titre, auteurs, doi : str
        Champs bruts utiles aux contrôles et au prompt.
    doi_normalise, uri_normalisee : str ou None
    titre_normalise, auteurs_normalises : str
    annee : int ou None
    titre_generique : bool
        Titre trop court ou dans la liste des titres génériques.
    priorite_portail : int
    """

    id_biblio: str
    titre: str
    auteurs: str
    doi: str
    doi_normalise: str | None
    uri_normalisee: str | None
    titre_normalise: str
    auteurs_normalises: str
    annee: int | None
    titre_generique: bool
    priorite_portail: int


def est_titre_generique(titre_normalise: str, configuration: Configuration) -> bool:
    """Dit si un titre normalisé est trop court ou générique pour être comparé seul.

    Paramètres
    ----------
    titre_normalise : str
    configuration : Configuration

    Renvoie
    -------
    bool
    """
    longueur_min = configuration.chaine["dedoublonnage"]["longueur_min_titre_significatif"]
    if len(titre_normalise) < longueur_min:
        return True
    return titre_normalise in set(configuration.filtres["dedoublonnage"]["titres_generiques"])


def preparer_notices(notices: pd.DataFrame, configuration: Configuration) -> dict[str, NoticeComparee]:
    """Calcule la forme normalisée de chaque notice, indexée par id_biblio.

    Paramètres
    ----------
    notices : pandas.DataFrame
    configuration : Configuration

    Renvoie
    -------
    dict
        id_biblio vers NoticeComparee, dans l'ordre du fichier.
    """
    parametres = configuration.chaine["dedoublonnage"]
    priorites = parametres["priorite_portails"]
    priorite_inconnue = parametres["priorite_portail_inconnu"]
    separateur = configuration.chaine["schema"]["separateur_auteurs"]
    comparees: dict[str, NoticeComparee] = {}
    for ligne in notices.itertuples(index=False):
        titre_normalise = normaliser_titre(ligne.titre)
        comparees[ligne.id_biblio] = NoticeComparee(
            id_biblio=ligne.id_biblio,
            titre=ligne.titre,
            auteurs=ligne.auteurs,
            doi=ligne.DOI,
            doi_normalise=normaliser_doi(ligne.DOI),
            uri_normalisee=normaliser_uri(ligne.uri),
            titre_normalise=titre_normalise,
            auteurs_normalises=normaliser_liste_auteurs(ligne.auteurs, separateur),
            annee=extraire_annee(ligne.date),
            titre_generique=est_titre_generique(titre_normalise, configuration),
            priorite_portail=priorites.get(ligne.portail.upper(), priorite_inconnue),
        )
    return comparees
