"""Collecte theses.fr : une requête par paire de mots, reprise après interruption, complément par NNT."""

from __future__ import annotations

import csv
import json
import logging
import random
import re
from pathlib import Path
from typing import Any

import requests

from bibliosig.collecte.couples import paires_de_mots
from bibliosig.collecte.http import attendre, masquer_secrets, ouvrir_session
from bibliosig.configuration import Configuration
from bibliosig.normalisation.schema import etiquette_theses

journal = logging.getLogger(__name__)

CHAMPS = [
    "titre",
    "auteur",
    "annee",
    "directeur",
    "etablissement",
    "discipline",
    "statut",
    "mots_cles",
    "resume_fr",
    "nnt",
    "url",
]
MOTIF_ANNEE = re.compile(r"(19|20)\d{2}")


def noms_personnes(valeur: Any) -> str:
    """Noms « Nom, Prénom » d'une liste de personnes de l'API, joints par ``; ``.

    Paramètres
    ----------
    valeur : list ou str

    Renvoie
    -------
    str
    """
    if isinstance(valeur, str):
        return valeur
    noms = []
    for personne in valeur or []:
        if isinstance(personne, dict):
            noms.append(f"{personne.get('nom', '') or ''}, {personne.get('prenom', '') or ''}".strip(", "))
        elif isinstance(personne, str):
            noms.append(personne)
    return "; ".join(nom for nom in noms if nom)


def libelles(valeurs: Any, cles: tuple[str, ...]) -> list[str]:
    """Libellés d'une liste de sujets (chaînes ou objets).

    Paramètres
    ----------
    valeurs : list
    cles : tuple of str
        Clés possibles du libellé dans un objet.

    Renvoie
    -------
    list of str
    """
    trouves = []
    for valeur in valeurs if isinstance(valeurs, list) else []:
        if isinstance(valeur, str):
            trouves.append(valeur)
        elif isinstance(valeur, dict):
            libelle = next((valeur.get(cle) for cle in cles if valeur.get(cle)), "")
            if libelle:
                trouves.append(libelle)
    return trouves


def lire_these(these: Any, parametres: dict[str, Any]) -> dict[str, str] | None:
    """Champs d'une thèse de l'API (formats de réponse variés), ou ``None`` sans titre.

    Paramètres
    ----------
    these : dict
    parametres : dict
        Section ``[theses]``.

    Renvoie
    -------
    dict ou None
    """
    if not isinstance(these, dict):
        return None
    titre = ""
    for cle in ("titrePrincipal", "titre", "title", "titres"):
        valeur = these.get(cle, "")
        titre = (
            valeur
            if isinstance(valeur, str)
            else (valeur.get("fr", "") or valeur.get("en", "") if isinstance(valeur, dict) else "")
        )
        if titre:
            break
    if not titre:
        return None
    auteur = next((noms_personnes(these[c]) for c in ("auteurs", "auteur", "author") if these.get(c)), "")
    annee = next(
        (
            these[c][:4]
            for c in ("dateSoutenance", "datePremiereInscriptionDoctorat", "date")
            if isinstance(these.get(c), str) and len(these[c]) >= 4
        ),
        "",
    )
    directeur = next(
        (
            noms_personnes(these[c])
            for c in ("directeursThese", "directeurs")
            if isinstance(these.get(c), list) and these[c]
        ),
        "",
    )
    etablissement = next(
        (
            these[c]
            for c in ("etabSoutenanceN", "etabSoutenance", "etablissement")
            if isinstance(these.get(c), str) and these[c]
        ),
        "",
    )
    sujets = these.get("sujets", {})
    mots = []
    if isinstance(sujets, dict):
        for langue in ("fr", "en"):
            mots += libelles(sujets.get(langue, []), ("libelle", "label", "nom"))
    else:
        mots += libelles(sujets, ("libelle", "label"))
    mots += libelles(these.get("sujetsRameau", []), ("libelle", "label"))
    mots += (
        [v for v in these.get("sujetsLibelle", []) if isinstance(v, str)]
        if isinstance(these.get("sujetsLibelle"), list)
        else []
    )
    resumes = these.get("resumes", {})
    resume = (
        (resumes.get("fr", "") or "")
        if isinstance(resumes, dict)
        else (resumes if isinstance(resumes, str) else "")
    )
    nnt = these.get("id", "") or these.get("nnt", "") or these.get("numSujet", "") or ""
    return {
        "titre": titre,
        "auteur": auteur,
        "annee": annee,
        "directeur": directeur,
        "etablissement": etablissement,
        "discipline": these.get("discipline", "") or "",
        "statut": these.get("status", "") or "",
        "mots_cles": "; ".join(mots),
        "resume_fr": resume[: parametres["longueur_max_resume"]],
        "nnt": nnt,
        "url": parametres["url_these"].format(nnt=nnt) if nnt else "",
    }


def lire_reponse(donnees: Any, parametres: dict[str, Any]) -> tuple[list[dict[str, str]], int]:
    """Thèses et total d'une réponse de recherche (objet ou liste).

    Paramètres
    ----------
    donnees : dict ou list
    parametres : dict

    Renvoie
    -------
    tuple
    """
    if isinstance(donnees, dict):
        total = donnees.get("totalHits", 0) or donnees.get("total", 0) or 0
        elements = (
            donnees.get("theses", [])
            or donnees.get("results", [])
            or donnees.get("data", [])
            or donnees.get("content", [])
            or []
        )
    elif isinstance(donnees, list):
        elements, total = donnees, len(donnees)
    else:
        return [], 0
    theses = [t for t in (lire_these(e, parametres) for e in elements) if t]
    return theses, total


def demander(session: requests.Session, params: dict[str, Any], parametres: dict[str, Any]) -> Any | None:
    """Requête de recherche avec nouvelles tentatives ; ``None`` après échec.

    Paramètres
    ----------
    session : requests.Session
    params : dict
    parametres : dict

    Renvoie
    -------
    dict, list ou None
    """
    for tentative in range(1, parametres["tentatives_max"] + 1):
        try:
            reponse = session.get(parametres["url"], params=params, timeout=parametres["delai_secondes"])
        except requests.RequestException as erreur:
            journal.warning("theses.fr : %s (tentative %d)", masquer_secrets(erreur), tentative)
            attendre(parametres["pause_sur_erreur"])
            continue
        if reponse.status_code == 200:
            return reponse.json()
        attendre(parametres["pause_sur_erreur"] * (tentative if reponse.status_code == 429 else 1))
    return None


def chercher_paire(
    session: requests.Session, mot_a: str, mot_b: str, parametres: dict[str, Any]
) -> list[dict[str, str]]:
    """Toutes les thèses d'une paire de mots, dans la limite prévue.

    Paramètres
    ----------
    session : requests.Session
    mot_a, mot_b : str
    parametres : dict

    Renvoie
    -------
    list of dict
    """
    trouvees: list[dict[str, str]] = []
    debut = 0
    limite = parametres["notices_max_par_couple"]
    while len(trouvees) < limite:
        donnees = demander(
            session,
            {
                "q": f'"{mot_a}" AND "{mot_b}"',
                "debut": debut,
                "nombre": parametres["notices_par_page"],
                "tri": "pertinence",
            },
            parametres,
        )
        if donnees is None:
            break
        theses, total = lire_reponse(donnees, parametres)
        if (debut == 0 and total == 0) or not theses:
            break
        trouvees.extend(theses)
        if len(trouvees) >= total or len(theses) < parametres["notices_par_page"]:
            break
        debut += len(theses)
        attendre(random.uniform(parametres["pause_min"], parametres["pause_max"]))
    return trouvees[:limite]


def ecrire_paire(chemin: Path, theses: list[dict[str, str]]) -> None:
    """Fichier d'une paire de mots (séparateur point-virgule).

    Paramètres
    ----------
    chemin : Path
    theses : list of dict
    """
    with chemin.open("w", encoding="utf-8", newline="") as flux:
        ecrivain = csv.DictWriter(flux, fieldnames=CHAMPS, delimiter=";", extrasaction="ignore")
        ecrivain.writeheader()
        ecrivain.writerows(theses)


def collecter(
    configuration: Configuration, dossier: Path, limite_couples: int | None = None
) -> dict[str, Any]:
    """Interroge theses.fr pour chaque paire ; les paires déjà faites sont sautées à la reprise.

    Paramètres
    ----------
    configuration : Configuration
    dossier : Path
    limite_couples : int, optionnel

    Renvoie
    -------
    dict
    """
    parametres = configuration.plateformes["theses"]
    sortie = dossier / parametres["dossier"]
    sortie.mkdir(parents=True, exist_ok=True)
    chemin_reprise = sortie / parametres["fichier_reprise"]
    reprise = (
        json.loads(chemin_reprise.read_text(encoding="utf-8"))
        if chemin_reprise.exists()
        else {"completed": []}
    )
    session = ouvrir_session(configuration, Accept="application/json")
    statistiques, total = [], 0
    for mot_a, mot_b in paires_de_mots(configuration, "theses")[:limite_couples]:
        cle = f"{mot_a}||{mot_b}"
        if cle in reprise["completed"]:
            continue
        theses = chercher_paire(session, mot_a, mot_b, parametres)
        if theses:
            ecrire_paire(sortie / f"{etiquette_theses(mot_a)}_X_{etiquette_theses(mot_b)}.csv", theses)
        statistiques.append({"groupe_A": mot_a, "groupe_B": mot_b, "num_found": len(theses)})
        total += len(theses)
        reprise["completed"].append(cle)
        chemin_reprise.write_text(json.dumps(reprise, ensure_ascii=False, indent=2), encoding="utf-8")
        attendre(parametres["pause_entre_couples"])
    with (sortie / "theses_matrix_stats.csv").open("w", encoding="utf-8-sig", newline="") as flux:
        ecrivain = csv.DictWriter(flux, fieldnames=["groupe_A", "groupe_B", "num_found"])
        ecrivain.writeheader()
        ecrivain.writerows(statistiques)
    return {"paires": len(statistiques), "theses": total}


def completer_par_nnt(configuration: Configuration, dossier: Path) -> int:
    """Complète les fichiers par paire en interrogeant l'API par NNT.

    La date et le résumé de l'API remplacent ceux du fichier ;
    auteur, titre et mots-clés ne sont remplis que s'ils sont vides.

    Paramètres
    ----------
    configuration : Configuration
    dossier : Path

    Renvoie
    -------
    int
        Nombre de thèses dont la date a été remplacée.
    """
    parametres = configuration.plateformes["theses"]
    session = ouvrir_session(configuration, Accept="application/json")
    completees = 0
    for chemin in sorted((dossier / parametres["dossier"]).glob("*_X_*.csv")):
        with chemin.open(encoding="utf-8", newline="") as flux:
            theses = list(csv.DictReader(flux, delimiter=";"))
        for these in theses:
            nnt = these.get("nnt", "").strip()
            donnees = demander(session, {"q": f"nnt:({nnt})", "nombre": 1}, parametres) if nnt else None
            liste = donnees.get("theses", []) if isinstance(donnees, dict) else (donnees or [])
            if not liste:
                continue
            source = liste[0]
            date = next(
                (
                    m.group()
                    for c in ("dateSoutenance", "datePremiereInscriptionDoctorat", "date")
                    if isinstance(source.get(c), str) and (m := MOTIF_ANNEE.search(source[c]))
                ),
                "",
            )
            if date:
                these["annee"] = date
                completees += 1
            resumes = source.get("resumes", {})
            resume = (
                (resumes.get("fr", "") or resumes.get("en", "") or "")[: parametres["longueur_max_resume"]]
                if isinstance(resumes, dict)
                else ""
            )
            if resume:
                these["resume_fr"] = resume
            sujets = source.get("sujets", {})
            complement = {
                "mots_cles": "; ".join(
                    mot
                    for langue in ("fr", "en")
                    for mot in (
                        libelles(sujets.get(langue, []), ("libelle", "label"))
                        if isinstance(sujets, dict)
                        else []
                    )
                ),
                "auteur": noms_personnes(source.get("auteurs", [])).replace("; ", " || "),
                "titre": source.get("titrePrincipal", "") or "",
            }
            for champ in ("mots_cles", "auteur", "titre"):
                if not these.get(champ, "").strip() and complement[champ]:
                    these[champ] = complement[champ]
            attendre(parametres["pause_complement"])
        ecrire_paire(chemin, theses)
    return completees
