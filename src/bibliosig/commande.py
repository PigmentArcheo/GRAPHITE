"""Commande unique ``bibliosig`` : lance une étape de la chaîne ou toute la chaîne."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from bibliosig import __version__
from bibliosig.configuration import Chemins, charger_configuration, charger_fichier_env

journal = logging.getLogger("bibliosig")


def ajouter_options_communes(analyseur: argparse.ArgumentParser) -> None:
    """Ajoute les options de chemins et de journal à une sous-commande.

    Paramètres
    ----------
    analyseur : argparse.ArgumentParser
    """
    analyseur.add_argument("-h", "--aide", action="help", help="affiche cette aide")
    analyseur.add_argument("--config", type=Path, default=Path("config"), help="dossier de configuration")
    analyseur.add_argument("--donnees", type=Path, default=Path("data"), help="dossier des données")
    analyseur.add_argument("--sorties", type=Path, default=Path("out"), help="dossier des sorties")
    analyseur.add_argument("--bavard", action="store_true", help="journal détaillé")


def construire_analyseur() -> argparse.ArgumentParser:
    """Décrit les sous-commandes et leurs options.

    Renvoie
    -------
    argparse.ArgumentParser
    """
    analyseur = argparse.ArgumentParser(
        prog="bibliosig",
        description="Chaîne bibliométrique : collecte, nettoyage, classification, graphe et analyses.",
        add_help=False,
    )
    analyseur.add_argument("-h", "--aide", action="help", help="affiche cette aide")
    analyseur.add_argument(
        "--version", action="version", version=f"bibliosig {__version__}", help="affiche la version"
    )
    analyseur._optionals.title = "options"
    sous = analyseur.add_subparsers(dest="etape", required=True, metavar="étape", title="étapes")

    collecte = sous.add_parser("collecte", add_help=False, help="interroge les plateformes (réseau)")
    ajouter_options_communes(collecte)
    collecte.add_argument(
        "plateformes",
        nargs="+",
        choices=["hal", "openalex", "persee", "sudoc", "theses", "frantiq"],
        help="plateformes à interroger",
    )
    collecte.add_argument("--openalex-cle", help="clé OpenAlex (sinon OPENALEX_API_KEY)")
    collecte.add_argument(
        "--persee-telecharger",
        action="store_true",
        help="télécharge les archives RDF des revues Persée avant l'indexation",
    )
    collecte.add_argument(
        "--limite-couples", type=int, default=None, help="nombre maximal de couples (essai)"
    )

    normalise = sous.add_parser("normalise", add_help=False, help="passe les collectes au schéma commun")
    ajouter_options_communes(normalise)

    corrige = sous.add_parser("corrige", add_help=False, help="applique les corrections manuelles")
    ajouter_options_communes(corrige)

    for nom, aide in (
        ("fusionne", "fusionne les six portails"),
        ("filtre", "filtres thématiques négatif puis positif"),
    ):
        ajouter_options_communes(sous.add_parser(nom, add_help=False, help=aide))

    graphe = sous.add_parser("graphe", add_help=False, help="écrit les fichiers d'import Neo4j")
    ajouter_options_communes(graphe)
    graphe.add_argument(
        "--importer", action="store_true", help="exécute aussi import.cypher dans Neo4j (option [neo4j])"
    )
    graphe.add_argument("--mot-de-passe-neo4j", default=None, help="sinon NEO4J_PASSWORD")

    dedoublonne = sous.add_parser("dedoublonne", add_help=False, help="regroupe les notices en œuvres")
    ajouter_options_communes(dedoublonne)
    dedoublonne.add_argument("--llm", action="store_true", help="avis du modèle sur les paires")
    dedoublonne.add_argument("--rejouer", action="store_true", help="sans appel au modèle")
    dedoublonne.add_argument("--seuil-titre", type=float, default=None)

    classe = sous.add_parser("classe", add_help=False, help="classification SIG (pré-filtre et modèle)")
    ajouter_options_communes(classe)
    classe.add_argument("--rejouer", action="store_true", help="relit les décisions de out/")
    classe.add_argument("--decisions", type=Path, default=None, help="dossier des décisions à rejouer")
    classe.add_argument("--limite", type=int, default=None, help="nombre maximal de notices")
    classe.add_argument("--sans-prefiltre", action="store_true")

    auteurs = sous.add_parser("auteurs", add_help=False, help="regroupe les formes de noms en personnes")
    ajouter_options_communes(auteurs)
    auteurs.add_argument("--rejouer", action="store_true", help="relit les décisions de out/")
    auteurs.add_argument("--decisions", type=Path, default=None, help="dossier des décisions à rejouer")
    auteurs.add_argument("--annotations", type=Path, default=None, help="décisions manuelles (auteurs)")
    auteurs.add_argument("--sans-llm", action="store_true")
    auteurs.add_argument("--limite-familles", type=int, default=None)

    analyses = sous.add_parser(
        "analyses", add_help=False, help="tableaux et indicateurs des publications, concepts et co-auteurs"
    )
    ajouter_options_communes(analyses)
    analyses.add_argument(
        "--expressions-protegees",
        action="store_true",
        help="mots des titres : ajoute les synonymes de SIG et d'analyse spatiale",
    )

    figures = sous.add_parser("figures", add_help=False, help="figures simples des analyses")
    ajouter_options_communes(figures)

    zotero = sous.add_parser("zotero", add_help=False, help="envoie les notices vers Zotero (réseau)")
    ajouter_options_communes(zotero)
    zotero.add_argument("--fichier", type=Path, default=None, help="CSV à envoyer")
    zotero.add_argument("--cle", help="clé Zotero (sinon ZOTERO_API_KEY)")
    zotero.add_argument("--bibliotheque", help="identifiant de bibliothèque (sinon ZOTERO_LIBRARY_ID)")
    zotero.add_argument("--type-bibliotheque", choices=["user", "group"], default="user")
    zotero.add_argument("--collection", default=None, help="clé de collection Zotero")
    zotero.add_argument("--par-oeuvre", action="store_true", help="une notice par œuvre")
    zotero.add_argument("--filtre-sig", action="store_true", help="seulement les notices SIG")
    zotero.add_argument("--limite", type=int, default=0)
    zotero.add_argument("--purge", action="store_true", help="supprime tous les éléments (irréversible)")
    zotero.add_argument("--confirmer", default="", help="mot de confirmation exigé par --purge")
    zotero.add_argument("--essai-a-blanc", "--dry-run", action="store_true", dest="essai_a_blanc")

    tout = sous.add_parser("tout", add_help=False, help="enchaîne les étapes hors réseau")
    ajouter_options_communes(tout)
    tout.add_argument("--rejouer", action="store_true", help="sans modèle de langue")
    tout.add_argument("--annotations", type=Path, default=None)
    return analyseur


def lancer_etape(etape: str, arguments: argparse.Namespace) -> Any:
    """Exécute une étape avec les options reçues.

    Paramètres
    ----------
    etape : str
    arguments : argparse.Namespace

    Renvoie
    -------
    Any
        Bilan de l'étape.
    """
    configuration = charger_configuration(arguments.config)
    chemins = Chemins(arguments.donnees, arguments.sorties, configuration.chaine["fichiers"])
    rejouer = getattr(arguments, "rejouer", False)
    decisions = getattr(arguments, "decisions", None) or arguments.sorties

    if etape == "collecte":
        from bibliosig.collecte.etape import executer as collecter

        return collecter(configuration, chemins, arguments)
    if etape == "normalise":
        from bibliosig.normalisation.etape import executer as normaliser

        return normaliser(configuration, chemins)
    if etape == "corrige":
        from bibliosig.normalisation.corrections import executer as corriger

        return corriger(configuration, chemins)
    if etape == "fusionne":
        from bibliosig.fusion.etape import executer as fusionner

        return fusionner(configuration, chemins)
    if etape == "filtre":
        from bibliosig.filtrage.etape import executer as filtrer

        return filtrer(configuration, chemins)
    if etape == "dedoublonne":
        from bibliosig.dedoublonnage.etape import executer as dedoublonner

        return dedoublonner(
            configuration,
            chemins,
            utiliser_llm=getattr(arguments, "llm", False),
            rejouer=rejouer,
            seuil_titre=getattr(arguments, "seuil_titre", None),
        )
    if etape == "classe":
        from bibliosig.classification.etape import executer as classer

        return classer(
            configuration,
            chemins,
            rejouer=rejouer,
            dossier_decisions=decisions,
            limite=getattr(arguments, "limite", None),
            avec_prefiltre=not getattr(arguments, "sans_prefiltre", False),
        )
    if etape == "auteurs":
        from bibliosig.auteurs.etape import executer as regrouper_auteurs

        return regrouper_auteurs(
            configuration,
            chemins,
            annotations=arguments.annotations,
            rejouer=rejouer,
            dossier_decisions=decisions,
            sans_llm=getattr(arguments, "sans_llm", False),
            limite_familles=getattr(arguments, "limite_familles", None),
        )
    if etape == "graphe":
        from bibliosig.graphe.etape import executer as construire_graphe

        bilan = construire_graphe(configuration, chemins)
        if getattr(arguments, "importer", False):
            from bibliosig.graphe.import_neo4j import importer

            bilan["instructions_importees"] = importer(
                configuration, chemins.sortie("dossier_graphe"), arguments.mot_de_passe_neo4j
            )
        return bilan
    if etape == "analyses":
        from bibliosig.analyses.etape import executer as analyser

        return analyser(
            configuration,
            chemins,
            expressions_protegees=getattr(arguments, "expressions_protegees", False),
        )
    if etape == "figures":
        from bibliosig.figures.etape import executer as dessiner

        return dessiner(configuration, chemins)
    if etape == "zotero":
        from bibliosig.zotero.etape import executer as envoyer

        return envoyer(configuration, chemins, arguments)
    raise ValueError(f"Étape inconnue : {etape}")


def principal(argv: Sequence[str] | None = None) -> int:
    """Analyse la ligne de commande et lance l'étape demandée.

    Paramètres
    ----------
    argv : liste de str, optionnel
        Arguments ; par défaut ceux du processus.

    Renvoie
    -------
    int
        Code de sortie (0 si tout s'est bien passé).
    """
    arguments = construire_analyseur().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if arguments.bavard else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s : %(message)s",
    )
    charger_fichier_env(Path(".env"))
    etapes: list[str]
    if arguments.etape == "tout":
        etapes = ["fusionne", "filtre", "dedoublonne", "classe", "auteurs", "graphe", "analyses", "figures"]
    else:
        etapes = [arguments.etape]
    for etape in etapes:
        journal.info("Étape %s", etape)
        bilan = lancer_etape(etape, arguments)
        journal.debug(json.dumps(bilan, ensure_ascii=False, default=str))
    return 0
