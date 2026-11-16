"""Étape « normalise » : collectes des six portails → fichiers au schéma commun.

HAL, OpenAlex et Persée partent de leur fichier dédoublonné de collecte. SUDOC,
theses.fr et Frantiq partent des fichiers par paire de mots : chaque notice est
rattachée aux couples de concepts de toutes les paires qui l'ont trouvée.
Chaque portail reçoit ensuite ses id_biblio (préfixe et numéro sur six chiffres).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from bibliosig.collecte.couples import concept_par_mot
from bibliosig.communs.tableaux import ecrire_bilan, ecrire_csv, lire_csv_texte
from bibliosig.configuration import Chemins, Configuration
from bibliosig.normalisation import schema
from bibliosig.normalisation.corrections import appliquer_corrections_fichier

journal = logging.getLogger(__name__)

PORTAILS_OU = ("hal", "openalex", "persee")
PORTAILS_TERME_A_TERME = ("sudoc", "theses", "frantiq")


def identifiant(prefixe: str, numero: int) -> str:
    """Identifiant au schéma commun : préfixe et numéro sur six chiffres.

    Paramètres
    ----------
    prefixe : str
    numero : int

    Renvoie
    -------
    str
    """
    return f"{prefixe}{numero:06d}"


def construire(
    collecte: pd.DataFrame,
    prefixe: str,
    champ_obligatoire: str,
    construire_ligne: Callable[[pd.Series], dict[str, str]],
) -> pd.DataFrame:
    """Applique une règle de passage au schéma à chaque notice de collecte.

    Le numéro suit le rang dans la collecte, notices ignorées comprises ;
    un numéro peut donc manquer dans la suite.

    Paramètres
    ----------
    collecte : pandas.DataFrame
    prefixe : str
    champ_obligatoire : str
        Notice ignorée si ce champ est vide.
    construire_ligne : callable
        Notice de collecte → champs du schéma (sans id_biblio).

    Renvoie
    -------
    pandas.DataFrame
    """
    lignes = []
    for rang, (_, notice) in enumerate(collecte.iterrows(), start=1):
        if not str(notice.get(champ_obligatoire, "")).strip():
            continue
        lignes.append({"id_biblio": identifiant(prefixe, rang), **construire_ligne(notice)})
    return pd.DataFrame(lignes)


def normaliser_hal(collecte: pd.DataFrame, parametres: dict[str, Any]) -> pd.DataFrame:
    """Notices HAL dédoublonnées → schéma commun.

    Paramètres
    ----------
    collecte : pandas.DataFrame
        ``hal_matrix_dedup_100.csv``.
    parametres : dict
        Section ``[normalisation.hal]``.

    Renvoie
    -------
    pandas.DataFrame
    """

    def ligne(notice: pd.Series) -> dict[str, str]:
        return {
            "portail": parametres["portail"],
            "id_portail": notice.get("halId_s", "").strip(),
            "DOI": notice.get("doiId_s", notice.get("DOI", "")).strip(),
            "uri": notice.get("uri_s", "").strip(),
            "auteurs": schema.joindre_auteurs_barre(notice.get("authFullName_s", "")),
            "titre": notice.get("title_s", "").strip(),
            "resume": schema.premier_resume(notice.get("abstract_s", "")),
            "date": schema.annee(notice.get("producedDateY_i", "")),
            "mots_cles": schema.mots_cles_hal(notice.get("keyword_s", "")),
            "AxB": notice.get("combinaisons_AB", "").strip(),
            "type": parametres["types"].get(
                notice.get("docType_s", "").strip().upper(), parametres["type_inconnu"]
            ),
        }

    return construire(collecte, parametres["prefixe"], "halId_s", ligne)


def normaliser_openalex(collecte: pd.DataFrame, parametres: dict[str, Any]) -> pd.DataFrame:
    """Notices OpenAlex dédoublonnées → schéma commun.

    Paramètres
    ----------
    collecte : pandas.DataFrame
        ``openalex_matrix_dedup.csv``.
    parametres : dict
        Section ``[normalisation.openalex]``.

    Renvoie
    -------
    pandas.DataFrame
    """

    def ligne(notice: pd.Series) -> dict[str, str]:
        return {
            "portail": parametres["portail"],
            "id_portail": notice.get("id", "").strip(),
            "DOI": notice.get("doi", "").strip(),
            "uri": notice.get("primary_location.landing_page_url", "").strip(),
            "auteurs": schema.joindre_auteurs_barre_simple(notice.get("authorships", "")),
            "titre": notice.get("title", "").strip(),
            "resume": notice.get("abstract", "").strip(),
            "date": schema.annee(notice.get("publication_year", "")),
            "mots_cles": schema.mots_cles_barre(notice.get("keywords", "")),
            "AxB": notice.get("combinaisons_AB", "").strip(),
            "type": parametres["types"].get(
                notice.get("type", "").strip().lower(), parametres["type_inconnu"]
            ),
        }

    return construire(collecte, parametres["prefixe"], "id", ligne)


def normaliser_persee(collecte: pd.DataFrame, parametres: dict[str, Any]) -> pd.DataFrame:
    """Documents Persée dédoublonnés → schéma commun.

    Paramètres
    ----------
    collecte : pandas.DataFrame
        ``persee_matrix_dedup.csv``.
    parametres : dict
        Section ``[normalisation.persee]``.

    Renvoie
    -------
    pandas.DataFrame
    """

    def ligne(notice: pd.Series) -> dict[str, str]:
        return {
            "portail": parametres["portail"],
            "id_portail": notice.get("identifier", "").strip(),
            "DOI": "",
            "uri": notice.get("uri", "").strip(),
            "auteurs": schema.joindre_auteurs_barre_simple(notice.get("authors", "")),
            "titre": notice.get("title", "").strip(),
            "resume": notice.get("abstract", "").strip(),
            "date": schema.annee(notice.get("date", "")),
            "mots_cles": "",
            "AxB": notice.get("combinaisons_AB", "").strip(),
            "type": parametres["type_unique"],
        }

    return construire(collecte, parametres["prefixe"], "uri", ligne)


def paires_de_fichiers(
    portail: str, dossier: Path, configuration: Configuration
) -> list[tuple[str, str, Path]]:
    """Liste les fichiers par paire de mots d'un portail terme à terme.

    Paramètres
    ----------
    portail : {"sudoc", "theses", "frantiq"}
    dossier : Path
        Dossier des fichiers par paire.
    configuration : Configuration

    Renvoie
    -------
    list of tuple
        (mot A, mot B, fichier) pour chaque fichier présent, dans l'ordre des paires.
    """
    mots = configuration.plateformes["mots_terme_a_terme"]
    separateur = configuration.plateformes["normalisation"]["terme_a_terme"]["separateur_paire_fichier"]
    if portail == "theses":
        mots_a, mots_b = mots["theses_a"], mots["theses_b"]

        def nom(mot_a: str, mot_b: str) -> str:
            return f"{schema.etiquette_theses(mot_a)}_X_{schema.etiquette_theses(mot_b)}.csv"

    else:
        mots_a, mots_b = mots["sans_accents_a"], mots["sans_accents_b"]
        etiquettes = mots["etiquettes_fichiers"]

        def nom(mot_a: str, mot_b: str) -> str:
            etiquette_a = etiquettes.get(mot_a, mot_a.replace(" ", "_"))
            etiquette_b = etiquettes.get(mot_b, mot_b.replace(" ", "_"))
            return f"{etiquette_a}{separateur}{etiquette_b}.csv"

    return [
        (mot_a, mot_b, dossier / nom(mot_a, mot_b))
        for mot_a in mots_a
        for mot_b in mots_b
        if (dossier / nom(mot_a, mot_b)).exists()
    ]


def rattacher_aux_couples(portail: str, dossier: Path, configuration: Configuration) -> pd.DataFrame:
    """Réunit les fichiers par paire de mots et rattache chaque notice à ses couples.

    Une notice trouvée par plusieurs paires de mots reçoit tous les couples de
    concepts correspondants, sans doublon, triés, joints par `` || ``.

    Paramètres
    ----------
    portail : {"sudoc", "theses", "frantiq"}
    dossier : Path
    configuration : Configuration

    Renvoie
    -------
    pandas.DataFrame
        Schéma commun, sans id_biblio.

    Lève
    ----
    FileNotFoundError
        Si aucun fichier par paire n'est présent.
    """
    parametres = configuration.plateformes["normalisation"][portail]
    communs = configuration.plateformes["normalisation"]["terme_a_terme"]
    colonnes = parametres["colonnes"]
    separateur_auteurs = communs["separateurs_auteurs"][portail]
    concepts = concept_par_mot(configuration, "mots_theses" if portail == "theses" else "mots_sans_accents")
    fichiers = paires_de_fichiers(portail, dossier, configuration)
    if not fichiers:
        raise FileNotFoundError(f"Aucun fichier par paire de mots dans {dossier}")

    notices: dict[str, dict[str, str]] = {}
    couples: dict[str, set[str]] = {}
    for mot_a, mot_b, chemin in fichiers:
        couple = f"{concepts[mot_a]} × {concepts[mot_b]}"
        tableau = pd.read_csv(chemin, sep=communs["separateur_fichier"], dtype=str, keep_default_na=False)
        for _, ligne in tableau.iterrows():
            identifiant_portail = ligne.get(colonnes["id_portail"], "").strip()
            if not identifiant_portail:
                continue
            if parametres.get("retirer_zeros_initiaux"):
                identifiant_portail = identifiant_portail.lstrip("0")
            if identifiant_portail not in notices:
                type_portail = parametres.get("type_unique")
                if type_portail is None:
                    type_portail = parametres["types"].get(ligne.get(colonnes["type"], ""), "")
                notices[identifiant_portail] = {
                    "portail": parametres["portail"],
                    "id_portail": identifiant_portail,
                    "DOI": "",
                    "uri": ligne.get(colonnes["uri"], "") if "uri" in colonnes else "",
                    "auteurs": schema.auteurs_nom_prenom(
                        ligne.get(colonnes["auteurs"], ""), separateur_auteurs
                    ),
                    "titre": ligne.get(colonnes["titre"], "").strip(),
                    "resume": ligne.get(colonnes["resume"], "").strip(),
                    "date": ligne.get(colonnes["date"], "").strip(),
                    "mots_cles": ligne.get(colonnes["mots_cles"], "").strip(),
                    "type": type_portail,
                }
                couples[identifiant_portail] = set()
            couples[identifiant_portail].add(couple)
    lignes = [{**notice, "AxB": " || ".join(sorted(couples[cle]))} for cle, notice in notices.items()]
    colonnes_sortie = [c for c in configuration.chaine["schema"]["colonnes"] if c != "id_biblio"]
    return pd.DataFrame(lignes, columns=colonnes_sortie)


def attribuer_identifiants(notices: pd.DataFrame, prefixe: str) -> pd.DataFrame:
    """Ajoute en tête les id_biblio, dans l'ordre du fichier.

    Paramètres
    ----------
    notices : pandas.DataFrame
    prefixe : str

    Renvoie
    -------
    pandas.DataFrame
    """
    resultat = notices.copy()
    resultat.insert(0, "id_biblio", [identifiant(prefixe, n) for n in range(1, len(notices) + 1)])
    return resultat


def normaliser_portail(portail: str, configuration: Configuration, chemins: Chemins) -> pd.DataFrame | None:
    """Passe la collecte d'un portail au schéma commun, si elle est présente.

    Paramètres
    ----------
    portail : str
    configuration : Configuration
    chemins : Chemins

    Renvoie
    -------
    pandas.DataFrame ou None
        ``None`` si la collecte du portail est absente.
    """
    dossier_collecte = chemins.donnees / configuration.plateformes["dossiers"]["collecte"]
    parametres = configuration.plateformes["normalisation"][portail]
    if portail in PORTAILS_OU:
        chemin = dossier_collecte / configuration.plateformes[portail]["fichier_dedoublonne"]
        if not chemin.exists():
            return None
        regles = {"hal": normaliser_hal, "openalex": normaliser_openalex, "persee": normaliser_persee}
        notices = regles[portail](lire_csv_texte(chemin), parametres)
    else:
        dossier = dossier_collecte / configuration.plateformes[portail]["dossier"]
        deja_rattachees = chemins.donnees / f"{portail}_restructure_ok.csv"
        if dossier.exists():
            notices = attribuer_identifiants(
                rattacher_aux_couples(portail, dossier, configuration), parametres["prefixe"]
            )
        elif deja_rattachees.exists():
            notices = attribuer_identifiants(lire_csv_texte(deja_rattachees), parametres["prefixe"])
        else:
            return None
    colonnes = configuration.chaine["schema"]["colonnes"]
    return notices[colonnes]


def executer(configuration: Configuration, chemins: Chemins) -> dict[str, Any]:
    """Écrit ``<portail>_restructure.csv`` dans le dossier des données pour chaque portail collecté.

    Paramètres
    ----------
    configuration : Configuration
    chemins : Chemins

    Renvoie
    -------
    dict
        Nombre de notices par portail ; portails sans collecte.
    """
    bilan: dict[str, Any] = {"notices": {}, "absents": []}
    for portail in (*PORTAILS_OU, *PORTAILS_TERME_A_TERME):
        notices = normaliser_portail(portail, configuration, chemins)
        if notices is None:
            bilan["absents"].append(portail)
            continue
        chemin = chemins.donnees / configuration.plateformes["normalisation"][portail]["fichier_restructure"]
        ecrire_csv(notices, chemin)
        bilan["notices"][portail] = len(appliquer_corrections_fichier(chemin, configuration, chemins))
    journal.info("Normalisation : %s", bilan["notices"])
    ecrire_bilan(chemins.sortie("dossier_bilans"), "normalisation", bilan)
    return bilan
