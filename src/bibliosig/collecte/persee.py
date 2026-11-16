"""Collecte Persée : archives RDF des revues, index local, recherche par couple de concepts."""

from __future__ import annotations

import csv
import logging
import re
import tarfile
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from xml.sax import SAXException

import requests

from bibliosig.collecte.couples import Concept, couples_de_concepts
from bibliosig.collecte.hal import ecrire_statistiques
from bibliosig.collecte.http import attendre, masquer_secrets, ouvrir_session
from bibliosig.collecte.registre import RegistreNotices
from bibliosig.configuration import Configuration

journal = logging.getLogger(__name__)

CHAMPS_INDEX = [
    "uri",
    "identifier",
    "title",
    "abstract",
    "toc",
    "date",
    "authors",
    "journal_title",
    "language",
    "collection",
]
EXTENSIONS_RDF = (".rdf", ".ttl", ".xml", ".n3")
FORMATS_RDF = ("xml", "turtle", "n3")
APOSTROPHES = {"’": "'", "‘": "'", "ʼ": "'", "`": "'", "´": "'", "“": '"', "”": '"'}


def nettoyer(valeur: object) -> str:
    """Texte d'un littéral RDF : apostrophes unifiées, forme NFC, espaces réduites.

    Paramètres
    ----------
    valeur : object

    Renvoie
    -------
    str
    """
    if valeur is None:
        return ""
    texte = str(valeur)
    for origine, remplacement in APOSTROPHES.items():
        texte = texte.replace(origine, remplacement)
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", texte)).strip()


def forme_recherche(texte: str) -> str:
    """Texte sans accents et en minuscules, pour la recherche locale.

    Paramètres
    ----------
    texte : str

    Renvoie
    -------
    str
    """
    decompose = unicodedata.normalize("NFD", nettoyer(texte))
    return "".join(car for car in decompose if unicodedata.category(car) != "Mn").lower()


def motif_terme(terme: str) -> re.Pattern[str]:
    """Expression d'un terme en mot entier, sous sa forme de recherche.

    Paramètres
    ----------
    terme : str

    Renvoie
    -------
    re.Pattern
    """
    return re.compile(r"\b" + re.escape(forme_recherche(terme)) + r"\b")


def telecharger_collection(code: str, url: str, dossier: Path, configuration: Configuration) -> Path | None:
    """Télécharge l'archive RDF d'une revue, sauf si elle est déjà présente.

    Paramètres
    ----------
    code, url : str
    dossier : Path
    configuration : Configuration

    Renvoie
    -------
    Path ou None
    """
    dossier.mkdir(parents=True, exist_ok=True)
    archive = dossier / f"{code}.tar.gz"
    if archive.exists():
        return archive
    parametres = configuration.plateformes["persee"]
    try:
        with ouvrir_session(configuration).get(
            url, stream=True, timeout=parametres["delai_telechargement_secondes"]
        ) as reponse:
            reponse.raise_for_status()
            with archive.open("wb") as flux:
                for morceau in reponse.iter_content(chunk_size=65536):
                    flux.write(morceau)
    except requests.RequestException as erreur:
        journal.error("Téléchargement de %s impossible : %s", code, masquer_secrets(erreur))
        archive.unlink(missing_ok=True)
        return None
    return archive


def contenus_rdf(archive: Path) -> list[bytes]:
    """Fichiers RDF d'une archive, lus en mémoire (rien n'est extrait sur le disque).

    Paramètres
    ----------
    archive : Path

    Renvoie
    -------
    list of bytes
    """
    contenus = []
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for membre in tar.getmembers():
                if membre.isfile() and membre.name.endswith(EXTENSIONS_RDF):
                    flux = tar.extractfile(membre)
                    if flux is not None:
                        contenus.append(flux.read())
    except (tarfile.TarError, OSError) as erreur:
        journal.error("Archive illisible %s : %s", archive.name, erreur)
    return contenus


def documents_rdf(contenu: bytes, collection: str, parametres: dict[str, Any]) -> list[dict[str, str]]:
    """Documents Persée d'un fichier RDF : titre, résumé, sommaire, date, auteurs, revue.

    Paramètres
    ----------
    contenu : bytes
    collection : str
    parametres : dict
        Section ``[persee]``.

    Renvoie
    -------
    list of dict

    Lève
    ----
    ModuleNotFoundError
        Si rdflib n'est pas installé (option ``[persee]``).
    """
    from rdflib import Graph, Literal, Namespace, URIRef
    from rdflib.namespace import DCTERMS, FOAF, RDF

    bibo = Namespace("http://purl.org/ontology/bibo/")
    persee = Namespace("http://data.persee.fr/ontology/persee-ontology/")
    relateurs = Namespace("http://id.loc.gov/vocabulary/relators/")
    graphe = Graph()
    for format_rdf in FORMATS_RDF:
        try:
            graphe.parse(data=contenu, format=format_rdf)
            break
        except (ValueError, SyntaxError, SAXException):
            continue
    else:
        return []

    def litteraux(sujet: Any, predicat: Any) -> Iterable[Any]:
        return (objet for objet in graphe.objects(sujet, predicat) if isinstance(objet, Literal))

    def meilleur(sujet: Any, predicat: Any) -> str:
        valeurs = [((objet.language or "").lower(), nettoyer(objet)) for objet in litteraux(sujet, predicat)]
        valeurs = [(langue, texte) for langue, texte in valeurs if texte]
        for langue_voulue in parametres["langues_preferees"]:
            for langue, texte in valeurs:
                if langue == langue_voulue:
                    return texte
        return valeurs[0][1] if valeurs else ""

    def noms(noeud: Any) -> list[str]:
        trouves = [nettoyer(nom) for nom in graphe.objects(noeud, FOAF.name) if nettoyer(nom)]
        if trouves:
            return trouves
        texte = nettoyer(noeud)
        return [texte] if texte and not texte.startswith(parametres["prefixe_autorites"]) else []

    sujets = set()
    for type_document in (
        bibo.Document,
        bibo.Article,
        URIRef("http://purl.org/ontology/bibo/AcademicArticle"),
    ):
        sujets.update(graphe.subjects(RDF.type, type_document))
    if not sujets:
        sujets.update(graphe.subjects(DCTERMS.title, None))

    documents = []
    for sujet in sujets:
        uri = str(sujet)
        if not (
            uri.startswith(parametres["prefixe_documents"]) and uri.endswith(parametres["suffixe_documents"])
        ):
            continue
        titre = meilleur(sujet, DCTERMS.title)
        if not titre:
            continue
        sommaire = list(
            dict.fromkeys(nettoyer(o) for o in litteraux(sujet, DCTERMS.tableOfContents) if nettoyer(o))
        )
        identifiant = next(
            (nettoyer(o) for o in graphe.objects(sujet, DCTERMS.identifier) if nettoyer(o)), ""
        )
        date = ""
        for predicat in (persee.dateOfPrintPublication, DCTERMS.date, DCTERMS.issued):
            date = next((nettoyer(o)[:4] for o in graphe.objects(sujet, predicat) if nettoyer(o)), "")
            if date:
                break
        langue = next((nettoyer(o) for o in graphe.objects(sujet, DCTERMS.language) if nettoyer(o)), "")
        auteurs = [nom for noeud in graphe.objects(sujet, relateurs.aut) for nom in noms(noeud)]
        if not auteurs:
            for createur in graphe.objects(sujet, DCTERMS.creator):
                if not isinstance(createur, Literal):
                    auteurs.extend(noms(createur))
                elif nettoyer(createur):
                    auteurs.append(nettoyer(createur))
        revue = collection
        for numero in graphe.objects(sujet, DCTERMS.isPartOf):
            titre_revue = next(
                (
                    meilleur(j, DCTERMS.title)
                    for j in graphe.objects(numero, DCTERMS.isPartOf)
                    if meilleur(j, DCTERMS.title)
                ),
                "",
            )
            if titre_revue:
                revue = titre_revue
                break
        documents.append(
            {
                "uri": uri,
                "identifier": identifiant,
                "title": titre,
                "abstract": meilleur(sujet, DCTERMS.abstract),
                "toc": " || ".join(sommaire),
                "date": date,
                "authors": " | ".join(dict.fromkeys(a for a in auteurs if a)),
                "journal_title": revue,
                "language": langue,
                "collection": collection,
            }
        )
    return documents


def construire_index(configuration: Configuration, dossier: Path, telecharger: bool) -> int:
    """Construit l'index local des documents de toutes les revues.

    Paramètres
    ----------
    configuration : Configuration
    dossier : Path
    telecharger : bool
        Télécharge les archives absentes.

    Renvoie
    -------
    int
        Nombre de documents indexés.
    """
    parametres = configuration.plateformes["persee"]
    dossier_archives = dossier / parametres["dossier_archives"]
    total = 0
    with (dossier / parametres["fichier_index"]).open("w", newline="", encoding="utf-8-sig") as flux:
        ecrivain = csv.DictWriter(flux, fieldnames=CHAMPS_INDEX, extrasaction="ignore")
        ecrivain.writeheader()
        for code, (nom, url) in parametres["collections"].items():
            archive = dossier_archives / f"{code}.tar.gz"
            if telecharger:
                archive = telecharger_collection(code, url, dossier_archives, configuration)
            if archive is None or not archive.exists():
                continue
            vus: set[str] = set()
            documents = []
            for contenu in contenus_rdf(archive):
                for document in documents_rdf(contenu, nom, parametres):
                    if document["uri"] not in vus:
                        vus.add(document["uri"])
                        documents.append(document)
            ecrivain.writerows(documents)
            total += len(documents)
            journal.info("%s : %d documents", code, len(documents))
            attendre(parametres["pause_entre_collections"])
    return total


def correspond(document: dict[str, str], concept: Concept) -> bool:
    """Le document (titre, résumé, sommaire) contient-il un terme du concept ?

    Paramètres
    ----------
    document : dict
    concept : Concept

    Renvoie
    -------
    bool
    """
    texte = forme_recherche(
        " ".join([document.get("title", ""), document.get("abstract", ""), document.get("toc", "")]).strip()
    )
    return any(motif_terme(terme).search(texte) for terme in concept.termes)


def termes_et_champs(document: dict[str, str], termes: tuple[str, ...]) -> tuple[str, str]:
    """Termes trouvés et champs où ils l'ont été.

    Paramètres
    ----------
    document : dict
    termes : tuple of str

    Renvoie
    -------
    tuple of str
    """
    formes = {
        champ: forme_recherche(document.get(nom, ""))
        for champ, nom in (("title", "title"), ("abstract", "abstract"), ("toc", "toc"))
    }
    trouves, champs = [], set()
    for terme in termes:
        motif = motif_terme(terme)
        dans = [champ for champ, texte in formes.items() if motif.search(texte)]
        if dans:
            trouves.append(terme)
            champs.update(dans)
    return " | ".join(trouves), " | ".join(sorted(champs))


def rechercher(configuration: Configuration, dossier: Path) -> dict[str, Any]:
    """Recherche locale de chaque couple A × B dans l'index et écrit les fichiers de collecte.

    Paramètres
    ----------
    configuration : Configuration
    dossier : Path

    Renvoie
    -------
    dict
    """
    parametres = configuration.plateformes["persee"]
    with (dossier / parametres["fichier_index"]).open(newline="", encoding="utf-8-sig") as flux:
        documents = [dict(ligne) for ligne in csv.DictReader(flux)]
    registre = RegistreNotices("uri")
    statistiques, lignes = [], 0
    entetes = [
        "groupe_A",
        "termes_A_matchés",
        "groupe_B",
        "termes_B_matchés",
        "champ_match",
        "query_rank",
        *CHAMPS_INDEX,
    ]
    with (dossier / parametres["fichier_resultats"]).open("w", newline="", encoding="utf-8-sig") as flux:
        ecrivain = csv.DictWriter(flux, fieldnames=entetes, extrasaction="ignore")
        ecrivain.writeheader()
        for concept_a, concept_b in couples_de_concepts(configuration, "persee"):
            trouves = [d for d in documents if correspond(d, concept_a) and correspond(d, concept_b)]
            statistiques.append(
                {"groupe_A": concept_a.libelle, "groupe_B": concept_b.libelle, "num_found": len(trouves)}
            )
            for rang, document in enumerate(trouves, start=1):
                termes_a, champs_a = termes_et_champs(document, concept_a.termes)
                termes_b, champs_b = termes_et_champs(document, concept_b.termes)
                champs_reunis = " | ".join(sorted(set(f"{champs_a} | {champs_b}".split(" | "))))
                champs = re.sub(r"^[ |]+|[ |]+$", "", champs_reunis)
                ecrivain.writerow(
                    {
                        "groupe_A": concept_a.libelle,
                        "termes_A_matchés": termes_a,
                        "groupe_B": concept_b.libelle,
                        "termes_B_matchés": termes_b,
                        "champ_match": champs,
                        "query_rank": rang,
                        **document,
                    }
                )
                lignes += 1
                registre.enregistrer(document["uri"], document, concept_a.libelle, concept_b.libelle)
    uniques = registre.ecrire(dossier / parametres["fichier_dedoublonne"], CHAMPS_INDEX)
    ecrire_statistiques(dossier / parametres["fichier_statistiques"], statistiques)
    return {"lignes": lignes, "notices_uniques": uniques, "couples": len(statistiques)}


def collecter(configuration: Configuration, dossier: Path, telecharger: bool) -> dict[str, Any]:
    """Index des revues (avec téléchargement si demandé), puis recherche par couple.

    Paramètres
    ----------
    configuration : Configuration
    dossier : Path
    telecharger : bool

    Renvoie
    -------
    dict
    """
    dossier.mkdir(parents=True, exist_ok=True)
    indexes = construire_index(configuration, dossier, telecharger)
    return {"documents_indexes": indexes, **rechercher(configuration, dossier)}
