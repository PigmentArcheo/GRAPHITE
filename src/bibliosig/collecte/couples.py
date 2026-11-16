"""Concepts, couples de concepts A × B et mots interrogés terme à terme."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from bibliosig.configuration import Configuration


@dataclass(frozen=True)
class Concept:
    """Ensemble de termes français et anglais désigné par un libellé.

    Paramètres
    ----------
    libelle : str
    termes : tuple of str
        Termes dans l'ordre des requêtes « un OU par concept ».
    """

    libelle: str
    termes: tuple[str, ...]


def concepts(configuration: Configuration, bloc: str) -> list[Concept]:
    """Concepts d'un bloc, dans l'ordre de la configuration.

    Paramètres
    ----------
    configuration : Configuration
    bloc : {"bloc_a", "bloc_b"}

    Renvoie
    -------
    list of Concept
    """
    return [Concept(entree["libelle"], tuple(entree["termes"])) for entree in configuration.concepts[bloc]]


def concepts_plateforme(configuration: Configuration, plateforme: str) -> tuple[list[Concept], list[Concept]]:
    """Concepts A et B d'une plateforme interrogée « un OU par concept ».

    Persée réunit certains concepts B en un seul (termes mis bout à bout, à la
    place du premier).

    Paramètres
    ----------
    configuration : Configuration
    plateforme : {"hal", "openalex", "persee"}

    Renvoie
    -------
    tuple of list of Concept
    """
    bloc_a, bloc_b = concepts(configuration, "bloc_a"), concepts(configuration, "bloc_b")
    fusions = configuration.plateformes[plateforme].get("fusion_concepts_b", {})
    for libelle, membres in fusions.items():
        par_libelle = {concept.libelle: concept for concept in bloc_b}
        termes = tuple(terme for membre in membres for terme in par_libelle[membre].termes)
        rang = next(i for i, concept in enumerate(bloc_b) if concept.libelle == membres[0])
        bloc_b = [c for c in bloc_b if c.libelle not in membres[1:]]
        bloc_b[rang] = Concept(libelle, termes)
    return bloc_a, bloc_b


def couples_de_concepts(configuration: Configuration, plateforme: str) -> list[tuple[Concept, Concept]]:
    """Tous les couples A × B d'une plateforme, A d'abord.

    Paramètres
    ----------
    configuration : Configuration
    plateforme : str

    Renvoie
    -------
    list of tuple
    """
    bloc_a, bloc_b = concepts_plateforme(configuration, plateforme)
    return list(product(bloc_a, bloc_b))


def concept_par_mot(configuration: Configuration, cle_mots: str) -> dict[str, str]:
    """Libellé du concept de chaque mot interrogé terme à terme.

    Paramètres
    ----------
    configuration : Configuration
    cle_mots : {"mots_sans_accents", "mots_theses"}

    Renvoie
    -------
    dict
        Mot vers libellé du concept.
    """
    correspondance = {}
    for bloc in ("bloc_a", "bloc_b", "bloc_b_complementaire"):
        for entree in configuration.concepts.get(bloc, []):
            for mot in entree.get(cle_mots, []):
                correspondance[mot] = entree["libelle"]
    return correspondance


def paires_de_mots(configuration: Configuration, plateforme: str) -> list[tuple[str, str]]:
    """Les 19 × 14 paires de mots d'une plateforme terme à terme, dans l'ordre de la configuration (mots A, puis mots B).

    Paramètres
    ----------
    configuration : Configuration
    plateforme : {"sudoc", "theses", "frantiq"}

    Renvoie
    -------
    list of tuple
    """
    mots = configuration.plateformes["mots_terme_a_terme"]
    prefixe = "theses" if plateforme == "theses" else "sans_accents"
    return list(product(mots[f"{prefixe}_a"], mots[f"{prefixe}_b"]))
