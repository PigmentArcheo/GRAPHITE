"""Conversion d'une notice de la chaîne en élément Zotero."""

from __future__ import annotations

import html
import re
from typing import Any

MOTIF_BALISE = re.compile(r"<[^>]+>")
MOTIF_SEPARATEUR_MOTS_CLES = re.compile(r"\s*[|;]\s*")
MOTIF_ANNEE = re.compile(r"(1[0-9]{3}|2[0-9]{3})")


def nettoyer(texte: str) -> str:
    """Texte sans balises HTML, entités décodées, espaces réduites.

    Paramètres
    ----------
    texte : str

    Renvoie
    -------
    str
    """
    if not texte:
        return ""
    return re.sub(r"\s+", " ", html.unescape(MOTIF_BALISE.sub(" ", texte))).strip()


def separer(valeur: str, separateur: str = "||") -> list[str]:
    """Éléments non vides d'un champ multiple.

    Paramètres
    ----------
    valeur : str
    separateur : str

    Renvoie
    -------
    list of str
    """
    return [morceau.strip() for morceau in (valeur or "").split(separateur) if morceau.strip()]


def prenom_et_nom(auteur: str, particules: set[str]) -> tuple[str, str]:
    """Sépare prénom et nom ; « Nom, Prénom » est respecté, les particules restent au nom.

    Paramètres
    ----------
    auteur : str
    particules : set of str

    Renvoie
    -------
    tuple
        (prénom, nom).
    """
    auteur = nettoyer(auteur).replace(" ", " ")
    if "," in auteur:
        nom, prenom = auteur.split(",", 1)
        return prenom.strip(), nom.strip()
    mots = auteur.split()
    if len(mots) == 1:
        return "", mots[0]
    rang = len(mots) - 1
    while rang > 1 and mots[rang - 1].lower() in particules:
        rang -= 1
    return " ".join(mots[:rang]), " ".join(mots[rang:])


def annee(valeur: str) -> str:
    """Première année de quatre chiffres, sinon le champ tel quel.

    Paramètres
    ----------
    valeur : str

    Renvoie
    -------
    str
    """
    trouvee = MOTIF_ANNEE.search(valeur or "")
    return trouvee.group(1) if trouvee else (valeur or "").strip()


def element_zotero(
    notice: dict[str, str], parametres: dict[str, Any], collection: str | None = None
) -> dict[str, Any]:
    """Élément Zotero d'une notice : type, auteurs, étiquettes, champ Extra.

    L'id_biblio, en tête du champ Extra, sert à reconnaître les notices déjà
    présentes dans la bibliothèque.

    Paramètres
    ----------
    notice : dict
    parametres : dict
        Section ``[zotero]``.
    collection : str, optionnel
        Clé de collection Zotero.

    Renvoie
    -------
    dict
    """
    type_element = parametres["types"].get(
        (notice.get("type") or "").strip().upper(), parametres["type_par_defaut"]
    )
    particules = set(parametres["particules"])
    auteurs = []
    for auteur in separer(notice.get("auteurs", "")):
        prenom, nom = prenom_et_nom(auteur, particules)
        auteurs.append({"creatorType": "author", "firstName": prenom, "lastName": nom})
    brutes = [nettoyer(mot) for mot in MOTIF_SEPARATEUR_MOTS_CLES.split(notice.get("mots_cles", "") or "")]
    brutes += ["AxB:" + couple for couple in separer(notice.get("AxB", ""))]
    if notice.get("llm_label"):
        brutes.append("class:" + notice["llm_label"].strip())
    if notice.get("portail"):
        brutes.append("portail:" + notice["portail"].strip())
    vues: set[str] = set()
    etiquettes = []
    for etiquette in brutes:
        if (
            etiquette
            and len(etiquette) <= parametres["longueur_max_etiquette"]
            and etiquette.lower() not in vues
        ):
            vues.add(etiquette.lower())
            etiquettes.append({"tag": etiquette})
    extra = "\n".join(
        f"{cle}: {notice.get(cle, '')}" for cle in parametres["champs_extra"] if notice.get(cle)
    )
    element: dict[str, Any] = {
        "itemType": type_element,
        "title": nettoyer(notice.get("titre", "")),
        "creators": auteurs,
        "abstractNote": nettoyer(notice.get("resume", "")),
        "date": annee(notice.get("date", "")),
        "url": (notice.get("uri") or "").strip(),
        "tags": etiquettes,
        "extra": extra,
        "collections": [collection] if collection else [],
        "relations": {},
    }
    doi = (notice.get("DOI") or "").strip()
    if doi:
        if type_element in parametres["types_avec_doi"]:
            element["DOI"] = doi
        else:
            element["extra"] = f"DOI: {doi}\n{element['extra']}"
    return element
