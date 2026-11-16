"""Corrections manuelles de contenu, décrites dans un fichier CSV et rejouables.

Chaque ligne du fichier ``corrections_manuelles.csv`` décrit une opération sur un
fichier de la chaîne, repéré par son nom. La ligne visée est repérée par sa clé
(colonne ``cle``) : l'``id_biblio`` pour les notices, ou les colonnes indiquées
dans ``[corrections]`` de ``chaine.toml``, jointes par `` | `` :

- ``modifier`` : remplace la valeur d'une cellule (``cle``, ``colonne``) ;
- ``ajouter`` : crée la ligne si elle manque (après la ligne de clé ``apres``, ou
  à la fin), puis fixe la cellule ; une ligne de correction par cellule non vide ;
- ``deplacer`` : place la ligne juste après la ligne de clé ``apres`` (en tête si
  ``apres`` est vide) ;
- ``retirer`` : supprime la ligne.

Les ajouts et les déplacements s'appliquent dans l'ordre du fichier. Les
opérations sont idempotentes : réappliquer le fichier ne change plus rien.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from bibliosig.communs.tableaux import ecrire_bilan, ecrire_csv, lire_csv_texte
from bibliosig.configuration import Chemins, Configuration

journal = logging.getLogger(__name__)

COLONNES_CORRECTIONS = ["fichier", "operation", "cle", "colonne", "valeur", "apres"]
OPERATIONS = ("modifier", "ajouter", "deplacer", "retirer")
SEPARATEUR_CLE = " | "
MARQUE_BOM = b"\xef\xbb\xbf"


def colonnes_cle(nom_fichier: str, configuration: Configuration) -> list[str]:
    """Colonnes qui forment la clé des lignes d'un fichier.

    Paramètres
    ----------
    nom_fichier : str
    configuration : Configuration

    Renvoie
    -------
    list of str
    """
    return configuration.chaine["corrections"]["cles_par_fichier"].get(nom_fichier, ["id_biblio"])


def cles_lignes(tableau: pd.DataFrame, colonnes: list[str]) -> list[str]:
    """Clé de chaque ligne : valeurs des colonnes de clé jointes par `` | ``.

    Paramètres
    ----------
    tableau : pandas.DataFrame
    colonnes : list of str

    Renvoie
    -------
    list of str
    """
    return [SEPARATEUR_CLE.join(valeurs) for valeurs in zip(*(tableau[c] for c in colonnes), strict=True)]


def lire_corrections(chemins: Chemins) -> pd.DataFrame | None:
    """Lit le fichier des corrections manuelles s'il existe.

    Paramètres
    ----------
    chemins : Chemins

    Renvoie
    -------
    pandas.DataFrame ou None

    Lève
    ----
    ValueError
        Si une colonne attendue manque ou si une opération est inconnue.
    """
    chemin = chemins.entree("corrections_manuelles")
    if not chemin.exists():
        return None
    corrections = lire_csv_texte(chemin)
    manquantes = set(COLONNES_CORRECTIONS) - set(corrections.columns)
    if manquantes:
        raise ValueError(f"Colonnes absentes de {chemin.name} : {sorted(manquantes)}")
    inconnues = set(corrections["operation"]) - set(OPERATIONS)
    if inconnues:
        raise ValueError(f"Opérations inconnues dans {chemin.name} : {sorted(inconnues)}")
    return corrections


def placer_lignes(
    tableau: pd.DataFrame, positionnelles: pd.DataFrame, colonnes: list[str]
) -> tuple[pd.DataFrame, int]:
    """Applique les ajouts et les déplacements de lignes, dans l'ordre du fichier.

    Paramètres
    ----------
    tableau : pandas.DataFrame
    positionnelles : pandas.DataFrame
        Corrections ``ajouter`` et ``deplacer``.
    colonnes : list of str
        Colonnes de clé.

    Renvoie
    -------
    tableau : pandas.DataFrame
    modifications : int

    Lève
    ----
    KeyError
        Si une ligne à déplacer est absente.
    """
    lignes = tableau.reset_index(drop=True)
    ordre = list(lignes.index)
    etiquette_par_cle = {cle: rang for rang, cle in enumerate(cles_lignes(lignes, colonnes))}
    modifications = 0
    for correction in positionnelles.drop_duplicates(subset=["cle", "operation"]).itertuples(index=False):
        etiquette = etiquette_par_cle.get(correction.cle)
        if correction.operation == "ajouter":
            if etiquette is not None:
                continue
            etiquette = len(lignes)
            nouvelle = {colonne: "" for colonne in lignes.columns}
            nouvelle.update(zip(colonnes, correction.cle.split(SEPARATEUR_CLE), strict=True))
            lignes.loc[etiquette] = nouvelle
            etiquette_par_cle[correction.cle] = etiquette
            ancien_rang, rang_par_defaut = -1, len(ordre)
        else:
            if etiquette is None:
                raise KeyError(f"Ligne à déplacer absente : {correction.cle}")
            ancien_rang = ordre.index(etiquette)
            ordre.remove(etiquette)
            rang_par_defaut = 0
        apres = etiquette_par_cle.get(correction.apres) if correction.apres else None
        rang = ordre.index(apres) + 1 if apres is not None else rang_par_defaut
        ordre.insert(rang, etiquette)
        if rang != ancien_rang:
            modifications += 1
    return lignes.loc[ordre].reset_index(drop=True), modifications


def appliquer_corrections(
    tableau: pd.DataFrame, corrections: pd.DataFrame, colonnes: list[str]
) -> tuple[pd.DataFrame, int]:
    """Applique à un tableau les corrections qui le concernent.

    Paramètres
    ----------
    tableau : pandas.DataFrame
        Tableau de chaînes.
    corrections : pandas.DataFrame
        Corrections déjà réduites à ce tableau.
    colonnes : list of str
        Colonnes de clé.

    Renvoie
    -------
    tableau : pandas.DataFrame
    modifications : int
        Nombre de cellules ou de lignes effectivement changées.

    Lève
    ----
    KeyError
        Si une correction vise une ligne ou une colonne absente.
    """
    modifications = 0
    a_retirer = set(corrections.loc[corrections["operation"] == "retirer", "cle"])
    if a_retirer:
        presentes = pd.Series(cles_lignes(tableau, colonnes), index=tableau.index).isin(a_retirer)
        modifications += int(presentes.sum())
        tableau = tableau[~presentes]

    positionnelles = corrections[corrections["operation"].isin(["ajouter", "deplacer"])]
    tableau, placements = placer_lignes(tableau, positionnelles, colonnes)
    modifications += placements

    position = {cle: rang for rang, cle in enumerate(cles_lignes(tableau, colonnes))}
    cellules = corrections[corrections["operation"].isin(["modifier", "ajouter"])]
    for correction in cellules.itertuples(index=False):
        if correction.colonne not in tableau.columns:
            raise KeyError(f"Colonne inconnue « {correction.colonne} » dans {correction.fichier}")
        if correction.cle not in position:
            raise KeyError(f"Ligne {correction.cle} absente de {correction.fichier}")
        rang = position[correction.cle]
        if tableau.at[rang, correction.colonne] != correction.valeur:
            tableau.at[rang, correction.colonne] = correction.valeur
            modifications += 1
    return tableau, modifications


def appliquer_corrections_fichier(
    chemin: Path, configuration: Configuration, chemins: Chemins
) -> pd.DataFrame:
    """Applique les corrections prévues pour un fichier et le réécrit s'il change.

    Paramètres
    ----------
    chemin : Path
        Fichier CSV de la chaîne.
    configuration : Configuration
    chemins : Chemins

    Renvoie
    -------
    pandas.DataFrame
        Contenu du fichier après corrections.
    """
    tableau = lire_csv_texte(chemin)
    corrections = lire_corrections(chemins)
    if corrections is None:
        return tableau
    concernees = corrections[corrections["fichier"] == chemin.name]
    if concernees.empty:
        return tableau
    tableau, modifications = appliquer_corrections(
        tableau, concernees, colonnes_cle(chemin.name, configuration)
    )
    if modifications:
        avec_bom = chemin.read_bytes()[:3] == MARQUE_BOM
        ecrire_csv(tableau, chemin, avec_bom=avec_bom)
        journal.info("%s : %d corrections manuelles appliquées", chemin.name, modifications)
    return tableau


def plus_longue_sous_suite_croissante(valeurs: list[int]) -> set[int]:
    """Indices d'une plus longue sous-suite strictement croissante.

    Paramètres
    ----------
    valeurs : list of int

    Renvoie
    -------
    set of int
        Indices, dans ``valeurs``, des éléments de la sous-suite.
    """
    sommets: list[int] = []
    indices_sommets: list[int] = []
    precedents = [-1] * len(valeurs)
    for indice, valeur in enumerate(valeurs):
        gauche, droite = 0, len(sommets)
        while gauche < droite:
            milieu = (gauche + droite) // 2
            if sommets[milieu] < valeur:
                gauche = milieu + 1
            else:
                droite = milieu
        if gauche:
            precedents[indice] = indices_sommets[gauche - 1]
        if gauche == len(sommets):
            sommets.append(valeur)
            indices_sommets.append(indice)
        else:
            sommets[gauche] = valeur
            indices_sommets[gauche] = indice
    retenus: set[int] = set()
    courant = indices_sommets[-1] if indices_sommets else -1
    while courant != -1:
        retenus.add(courant)
        courant = precedents[courant]
    return retenus


def deduire_corrections(
    avant: pd.DataFrame, apres: pd.DataFrame, nom_fichier: str, colonnes: list[str]
) -> pd.DataFrame:
    """Décrit, sous forme de corrections, le passage d'un tableau à sa version retouchée.

    Les lignes déplacées sont celles qui sortent d'une plus longue suite de
    lignes restées dans le même ordre.

    Paramètres
    ----------
    avant : pandas.DataFrame
        Version produite par la chaîne.
    apres : pandas.DataFrame
        Version retouchée à la main.
    nom_fichier : str
        Nom du fichier à inscrire dans la colonne ``fichier``.
    colonnes : list of str
        Colonnes de clé.

    Renvoie
    -------
    pandas.DataFrame
        Lignes au format de ``corrections_manuelles.csv``.
    """
    corrections: list[dict[str, str]] = []

    def noter(operation: str, cle: str, colonne: str = "", valeur: str = "", apres_cle: str = "") -> None:
        corrections.append(
            {
                "fichier": nom_fichier,
                "operation": operation,
                "cle": cle,
                "colonne": colonne,
                "valeur": valeur,
                "apres": apres_cle,
            }
        )

    cles_avant = cles_lignes(avant, colonnes)
    cles_apres = cles_lignes(apres, colonnes)
    rang_avant = {cle: rang for rang, cle in enumerate(cles_avant)}
    presentes_apres = set(cles_apres)
    for cle in cles_avant:
        if cle not in presentes_apres:
            noter("retirer", cle)

    communes = [cle for cle in cles_apres if cle in rang_avant]
    stables = plus_longue_sous_suite_croissante([rang_avant[cle] for cle in communes])
    deplacees = {cle for indice, cle in enumerate(communes) if indice not in stables}

    for rang, cle in enumerate(cles_apres):
        precedente = cles_apres[rang - 1] if rang else ""
        valeurs = apres.iloc[rang]
        if cle not in rang_avant:
            for colonne in apres.columns:
                if colonne not in colonnes and valeurs[colonne] != "":
                    noter("ajouter", cle, colonne, valeurs[colonne], precedente)
            if all(valeurs[c] == "" for c in apres.columns if c not in colonnes):
                noter("ajouter", cle, colonnes[0], valeurs[colonnes[0]], precedente)
            continue
        if cle in deplacees:
            noter("deplacer", cle, apres_cle=precedente)
        ligne_avant = avant.iloc[rang_avant[cle]]
        for colonne in apres.columns:
            if colonne in avant.columns and ligne_avant[colonne] != valeurs[colonne]:
                noter("modifier", cle, colonne, valeurs[colonne])
    return pd.DataFrame(corrections, columns=COLONNES_CORRECTIONS)


def executer(configuration: Configuration, chemins: Chemins) -> dict[str, Any]:
    """Applique les corrections manuelles à tous les fichiers visés présents.

    Les fichiers sont cherchés dans le dossier des données puis dans celui des
    sorties.

    Paramètres
    ----------
    configuration : Configuration
    chemins : Chemins

    Renvoie
    -------
    dict
        Fichiers corrigés et fichiers visés introuvables.
    """
    corrections = lire_corrections(chemins)
    bilan: dict[str, Any] = {"fichiers_corriges": [], "fichiers_introuvables": []}
    if corrections is None:
        journal.info("Aucun fichier de corrections manuelles")
        return bilan
    for nom_fichier in corrections["fichier"].drop_duplicates():
        candidats = [chemins.donnees / nom_fichier, chemins.sorties / nom_fichier]
        chemin = next((candidat for candidat in candidats if candidat.exists()), None)
        if chemin is None:
            bilan["fichiers_introuvables"].append(nom_fichier)
            continue
        appliquer_corrections_fichier(chemin, configuration, chemins)
        bilan["fichiers_corriges"].append(nom_fichier)
    ecrire_bilan(chemins.sortie("dossier_bilans"), "corrections", bilan)
    return bilan
