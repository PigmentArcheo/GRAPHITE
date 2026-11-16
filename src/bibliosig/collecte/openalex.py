"""Collecte OpenAlex : une requête par couple (deux filtres de recherche), production française."""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import requests

from bibliosig.collecte.couples import Concept, couples_de_concepts
from bibliosig.collecte.detection import termes_trouves
from bibliosig.collecte.hal import ecrire_statistiques
from bibliosig.collecte.http import attendre, masquer_secrets, ouvrir_session
from bibliosig.collecte.registre import RegistreNotices
from bibliosig.configuration import Configuration

journal = logging.getLogger(__name__)


class CleOpenAlexRefusee(RuntimeError):
    """La requête de vérification de la clé OpenAlex a échoué."""


def ou_booleen(termes: tuple[str, ...]) -> str:
    """Termes réunis par OU ; une expression de plusieurs mots est mise entre guillemets.

    Paramètres
    ----------
    termes : tuple of str

    Renvoie
    -------
    str
    """
    return " OR ".join(f'"{terme}"' if " " in terme else terme for terme in termes)


def filtre_couple(concept_a: Concept, concept_b: Concept, parametres: dict[str, Any]) -> str:
    """Paramètre ``filter`` d'un couple : deux recherches liées par la virgule (ET).

    Seuls deux filtres ``title_and_abstract.search`` distincts imposent le ET
    entre les concepts ; ``search=`` ne le permet pas.

    Paramètres
    ----------
    concept_a, concept_b : Concept
    parametres : dict
        Section ``[openalex]``.

    Renvoie
    -------
    str
    """
    morceaux = [
        f"title_and_abstract.search:{ou_booleen(concept_a.termes)}",
        f"title_and_abstract.search:{ou_booleen(concept_b.termes)}",
    ]
    if parametres["code_pays"]:
        morceaux.append(f"institutions.country_code:{parametres['code_pays'].lower()}")
    morceaux.append(f"type:{parametres['types_documents']}")
    return ",".join(morceaux)


def appeler(
    session: requests.Session, params: dict[str, Any], parametres: dict[str, Any]
) -> dict[str, Any] | None:
    """Appel de l'API avec pauses sur limitation de débit et nouvelles tentatives.

    Paramètres
    ----------
    session : requests.Session
    params : dict
        Peut contenir ``api_key`` : jamais journalisée.
    parametres : dict

    Renvoie
    -------
    dict ou None
        ``None`` après échec définitif.
    """
    tentatives = parametres["tentatives_max"]
    for tentative in range(tentatives):
        try:
            reponse = session.get(parametres["url"], params=params, timeout=parametres["delai_secondes"])
        except requests.RequestException as erreur:
            journal.warning(
                "Réseau : %s (tentative %d/%d)", masquer_secrets(erreur), tentative + 1, tentatives
            )
            attendre(parametres["pause_erreur_reseau_secondes"])
            continue
        if reponse.status_code == 429:
            attendre(parametres["pause_limite_debit_secondes"] * (tentative + 1))
            continue
        if reponse.status_code != 200:
            journal.warning("HTTP %d : %s", reponse.status_code, masquer_secrets(reponse.text[:300]))
            return None
        return reponse.json()
    journal.error("Abandon après %d tentatives", tentatives)
    return None


def pages(
    session: requests.Session, params: dict[str, Any], parametres: dict[str, Any]
) -> Iterator[tuple[int | None, list[dict[str, Any]]]]:
    """Pages de résultats par curseur ; le total n'est donné qu'à la première.

    Paramètres
    ----------
    session : requests.Session
    params : dict
    parametres : dict

    Renvoie
    -------
    itérateur de tuple
        (total ou None, résultats de la page).
    """
    curseur = "*"
    premiere = True
    while True:
        donnees = appeler(
            session,
            {
                **params,
                "per_page": parametres["notices_par_page"],
                "cursor": curseur,
                "select": ",".join(parametres["champs_selectionnes"]),
            },
            parametres,
        )
        if donnees is None or not donnees.get("results"):
            return
        meta = donnees.get("meta", {})
        yield (meta.get("count") if premiere else None), donnees["results"]
        premiere = False
        curseur = meta.get("next_cursor")
        if not curseur:
            return
        attendre(parametres["pause_entre_pages"])


def resume_depuis_index(index_inverse: dict[str, list[int]] | None) -> str:
    """Résumé reconstruit depuis l'index inversé d'OpenAlex.

    Paramètres
    ----------
    index_inverse : dict ou None

    Renvoie
    -------
    str
    """
    if not index_inverse:
        return ""
    mots = {position: mot for mot, positions in index_inverse.items() for position in positions}
    return " ".join(mots[position] for position in sorted(mots))


def texte_recherche(oeuvre: dict[str, Any]) -> str:
    """Titre, résumé et mots-clés, pour relever les termes trouvés.

    Paramètres
    ----------
    oeuvre : dict

    Renvoie
    -------
    str
    """
    morceaux = [oeuvre.get("title") or "", resume_depuis_index(oeuvre.get("abstract_inverted_index"))]
    for mot in oeuvre.get("keywords") or []:
        libelle = mot.get("display_name") or mot.get("keyword") or ""
        if libelle:
            morceaux.append(libelle)
    return " ".join(morceaux)


def aplatir(oeuvre: dict[str, Any]) -> dict[str, Any]:
    """Œuvre OpenAlex → dict à plat pour le CSV.

    Paramètres
    ----------
    oeuvre : dict

    Renvoie
    -------
    dict
    """
    lieu = oeuvre.get("primary_location") or {}
    source = lieu.get("source") or {}
    acces = oeuvre.get("open_access") or {}
    noms, institutions = [], []
    for signature in oeuvre.get("authorships") or []:
        nom = (signature.get("author") or {}).get("display_name", "")
        if nom:
            noms.append(nom)
        for institution in signature.get("institutions") or []:
            libelle = institution.get("display_name", "")
            pays = (institution.get("country_code") or "").lower()
            if libelle:
                institutions.append(f"{libelle} ({pays})" if pays else libelle)
    mots_cles = " | ".join(
        mot.get("display_name") or mot.get("keyword", "")
        for mot in oeuvre.get("keywords") or []
        if mot.get("display_name") or mot.get("keyword")
    )
    themes = " | ".join(
        (
            f"{theme['display_name']} ({theme['score']:.3f})"
            if theme.get("score") is not None
            else theme["display_name"]
        )
        for theme in oeuvre.get("topics") or []
        if theme.get("display_name")
    )
    doi = oeuvre.get("doi") or ""
    return {
        "id": oeuvre.get("id", ""),
        "doi": doi.replace("https://doi.org/", "") if doi else "",
        "title": oeuvre.get("title", ""),
        "publication_year": oeuvre.get("publication_year", ""),
        "type": oeuvre.get("type", ""),
        "language": oeuvre.get("language", ""),
        "primary_location.source.display_name": source.get("display_name", ""),
        "primary_location.landing_page_url": lieu.get("landing_page_url", ""),
        "open_access.is_oa": acces.get("is_oa", ""),
        "open_access.oa_url": acces.get("oa_url", ""),
        "cited_by_count": oeuvre.get("cited_by_count", ""),
        "authorships": " | ".join(noms),
        "institutions": " | ".join(dict.fromkeys(institutions)),
        "keywords": mots_cles,
        "abstract": resume_depuis_index(oeuvre.get("abstract_inverted_index")),
        "topics": themes,
    }


def collecter(
    configuration: Configuration, dossier: Path, cle: str | None, limite_couples: int | None = None
) -> dict[str, Any]:
    """Interroge OpenAlex pour chaque couple A × B et écrit les trois fichiers de collecte.

    Paramètres
    ----------
    configuration : Configuration
    dossier : Path
    cle : str ou None
        Clé de l'API (argument ou ``OPENALEX_API_KEY``).
    limite_couples : int, optionnel

    Renvoie
    -------
    dict

    Lève
    ----
    CleOpenAlexRefusee
        Si la requête de vérification échoue.
    """
    parametres = configuration.plateformes["openalex"]
    session = ouvrir_session(configuration)
    authentification = {"api_key": cle} if cle else {}
    if (
        appeler(
            session,
            {"filter": parametres["filtre_verification"], "per_page": 1, **authentification},
            parametres,
        )
        is None
    ):
        raise CleOpenAlexRefusee("La vérification de l'accès à OpenAlex a échoué (clé ou réseau)")
    champs = parametres["champs_renvoyes"]
    registre = RegistreNotices(parametres["champ_identifiant"])
    couples = couples_de_concepts(configuration, "openalex")[:limite_couples]
    statistiques, lignes = [], 0
    dossier.mkdir(parents=True, exist_ok=True)
    entetes = ["groupe_A", "termes_A_matchés", "groupe_B", "termes_B_matchés", "query_rank", *champs]
    with (dossier / parametres["fichier_resultats"]).open("w", newline="", encoding="utf-8-sig") as flux:
        ecrivain = csv.DictWriter(flux, fieldnames=entetes, extrasaction="ignore")
        ecrivain.writeheader()
        for rang_couple, (concept_a, concept_b) in enumerate(couples, start=1):
            journal.info("[%d/%d] %s × %s", rang_couple, len(couples), concept_a.libelle, concept_b.libelle)
            params = {"filter": filtre_couple(concept_a, concept_b, parametres), **authentification}
            total, rang = 0, 1
            for numero_page, (compte, resultats) in enumerate(pages(session, params, parametres)):
                if numero_page == 0 and compte is not None:
                    total = compte
                for oeuvre in resultats:
                    texte = texte_recherche(oeuvre)
                    plat = aplatir(oeuvre)
                    ecrivain.writerow(
                        {
                            "groupe_A": concept_a.libelle,
                            "termes_A_matchés": termes_trouves(texte, concept_a.termes),
                            "groupe_B": concept_b.libelle,
                            "termes_B_matchés": termes_trouves(texte, concept_b.termes),
                            "query_rank": rang,
                            **plat,
                        }
                    )
                    rang += 1
                    lignes += 1
                    if plat["id"]:
                        registre.enregistrer(plat["id"], plat, concept_a.libelle, concept_b.libelle)
            statistiques.append(
                {"groupe_A": concept_a.libelle, "groupe_B": concept_b.libelle, "num_found": total}
            )
            attendre(parametres["pause_entre_couples"])
    uniques = registre.ecrire(dossier / parametres["fichier_dedoublonne"], champs)
    ecrire_statistiques(dossier / parametres["fichier_statistiques"], statistiques)
    return {"lignes": lignes, "notices_uniques": uniques, "couples": len(couples)}
