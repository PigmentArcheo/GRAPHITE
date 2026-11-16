"""Import facultatif du graphe dans une base Neo4j par le pilote officiel."""

from __future__ import annotations

import logging
from pathlib import Path

from bibliosig.configuration import Configuration, adresse_neo4j, valeur_secrete

journal = logging.getLogger(__name__)


def instructions(script: str) -> list[str]:
    """Instructions d'un script Cypher, sans commentaires ni lignes vides.

    Paramètres
    ----------
    script : str

    Renvoie
    -------
    list of str
    """
    lignes = [ligne for ligne in script.splitlines() if ligne.strip() and not ligne.lstrip().startswith("//")]
    return [instruction.strip() for instruction in "\n".join(lignes).split(";") if instruction.strip()]


def importer(configuration: Configuration, dossier_graphe: Path, mot_de_passe: str | None = None) -> int:
    """Exécute ``import.cypher`` dans la base configurée.

    Les CSV doivent déjà se trouver dans le dossier ``import`` de la base : les
    chemins ``file:///nodes_*.csv`` du script désignent ce dossier de Neo4j.

    Paramètres
    ----------
    configuration : Configuration
    dossier_graphe : Path
    mot_de_passe : str, optionnel
        Sinon ``NEO4J_PASSWORD``.

    Renvoie
    -------
    int
        Nombre d'instructions exécutées.

    Lève
    ----
    ModuleNotFoundError
        Si le pilote ``neo4j`` n'est pas installé (option ``[neo4j]``).
    ValueError
        Sans mot de passe.
    """
    from neo4j import GraphDatabase

    secret = valeur_secrete(mot_de_passe, "NEO4J_PASSWORD")
    if not secret:
        raise ValueError("Mot de passe Neo4j absent (--mot-de-passe-neo4j ou NEO4J_PASSWORD)")
    parametres = configuration.chaine["neo4j"]
    script = (dossier_graphe / "import.cypher").read_text(encoding="utf-8")
    liste = instructions(script)
    identifiants = (parametres["utilisateur"], secret)
    with (
        GraphDatabase.driver(adresse_neo4j(configuration), auth=identifiants) as pilote,
        pilote.session(database=parametres["base"]) as session,
    ):
        for instruction in liste:
            session.run(instruction).consume()
    journal.info("%d instructions Cypher exécutées", len(liste))
    return len(liste)
