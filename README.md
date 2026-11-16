# GRAPHITE — chaîne bibliométrique sur les SIG en archéologie

GRAPHITE provides `bibliosig`, a Python package that builds a bibliography on the use
of GIS (geographic information systems) in French archaeology. It harvests six
French-facing platforms (HAL, OpenAlex, Persée, SUDOC, theses.fr, Frantiq) from pairs
of concept sets, merges, filters, deduplicates and classifies the records (with
Mistral 7B through Ollama), groups author names into persons, builds a Neo4j graph,
computes tables and indicators from it, draws simple figures and sends the references
to Zotero. A new harvest gives different results because the platforms keep changing.
Data are not published here. The rest of this page is in French.

---

## But

`bibliosig` est une chaîne de traitement bibliométrique : elle collecte des notices
bibliographiques sur six plateformes à partir de concepts d'archéologie (bloc A) croisés
avec des concepts de géomatique et de numérique (bloc B), les nettoie, les classe, en
tire un graphe de publications, de personnes et de concepts, puis calcule des tableaux
et des indicateurs. Les paramètres (concepts, motifs, seuils, modèle) sont dans
`config/`, pas dans le code.

**Une nouvelle collecte donnera d'autres résultats.** Les plateformes ajoutent, corrigent
et retirent des notices chaque jour, et le modèle de langue ne répond pas deux fois de la
même façon. Le dépôt décrit une méthode ; il ne garantit pas des nombres.

## La chaîne

```
concepts A et B (ensembles de termes français et anglais, config/concepts.toml)
   │
   ├─ couples A × B : 10 × 10 = 100 couples
   │
   ├─ requêtes par plateforme
   │    HAL, OpenAlex, Persée : une requête par couple, chaque concept réuni par OU
   │    SUDOC, theses.fr, Frantiq : 19 mots A × 14 mots B (266 paires), puis
   │                               rattachement de chaque notice à ses couples A × B
   │
   ├─ normalise    passage au schéma commun (12 colonnes, dont AxB) et id_biblio
   ├─ corrige      retouches manuelles, rejouées depuis un fichier
   ├─ fusionne     six portails réunis (aucun doublon supprimé)
   ├─ filtre       passe négative (hors sujet évident), passe positive (vocabulaire archéologique)
   ├─ dedoublonne  notices regroupées en œuvres : DOI et URI, similarité des titres
   ├─ classe       SIG ou non : pré-filtre par motifs, puis Mistral 7B (Ollama)
   ├─ auteurs      formes de noms regroupées en personnes (règles, puis Mistral 7B)
   ├─ graphe       nœuds, relations et import.cypher pour Neo4j
   ├─ analyses     tableaux et indicateurs : publications, concepts, co-auteurs, mots des titres
   ├─ figures      une image simple par analyse
   └─ zotero       envoi vers une bibliothèque Zotero
```

Le détail de chaque étape, ses entrées et ses sorties est dans
[`docs/chaine_operatoire.md`](docs/chaine_operatoire.md).

### Concepts, couples et requêtes

L'unité de la collecte est le **concept** : un ensemble de termes. Le bloc A réunit 10
concepts archéologiques (37 termes), le bloc B 10 concepts géomatiques et numériques
(24 termes). On croise des **couples de concepts** A × B, et chaque notice garde son
couple dans la colonne `AxB` (« archéologie × SIG »).

- HAL, OpenAlex et Persée reçoivent **une requête par couple** : les termes d'un concept
  sont réunis par OU, car ces services refusent d'être interrogés terme à terme à cette
  échelle. Persée réunit deux concepts B (« cartographie/mapping/webSIG ») : 90 couples.
- SUDOC, theses.fr et Frantiq (scripts de Laura Louman) sont interrogés **terme à terme**
  avec les 19 mots français du bloc A et les 14 du bloc B, soit 266 paires ; chaque notice
  est ensuite rattachée aux couples de concepts de toutes les paires qui l'ont trouvée.
  Le bloc B de ces portails compte un concept de plus, « deep learning ».

## Installation

Python 3.11 ou plus récent.

```bash
git clone https://github.com/PigmentArcheo/GRAPHITE.git
cd GRAPHITE
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt     # environnement figé
pip install -e ".[dev]"             # commande bibliosig, tests, contrôle du style
```

Options : `[persee]` (rdflib, collecte Persée), `[figures]` (PyYAML, paramètres de la
figure des co-auteurs), `[neo4j]` (import direct dans Neo4j), `[llm]` (appels à Ollama).

## Accès requis

| Usage | Accès | Variable d'environnement |
|---|---|---|
| Collecte OpenAlex | clé de l'API | `OPENALEX_API_KEY` (ou `--openalex-cle`) |
| Étapes `dedoublonne --llm`, `classe`, `auteurs` | serveur Ollama avec `mistral` | `OLLAMA_URL` (défaut dans `config/chaine.toml`) |
| Import direct dans Neo4j | mot de passe de la base | `NEO4J_PASSWORD`, `NEO4J_URI` |
| Envoi vers Zotero | clé et identifiant de bibliothèque | `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID` |

Copier `.env.example` en `.env` (ignoré par Git) et le remplir. Un argument de la ligne
de commande prend le pas sur la variable. Aucun secret n'est écrit dans le code ni dans
les journaux.

## Utilisation pas à pas

Toutes les commandes se lancent à la racine du dépôt ; les données sont lues dans
`data/` et les sorties écrites dans `out/` (options `--donnees`, `--sorties`, `--config`).

```bash
bibliosig collecte hal openalex sudoc theses frantiq   # réseau
bibliosig collecte persee --persee-telecharger         # archives RDF des revues
bibliosig normalise        # data/collecte/… → data/<portail>_restructure.csv
bibliosig corrige          # applique data/corrections_manuelles.csv
bibliosig fusionne
bibliosig filtre
bibliosig dedoublonne --llm
bibliosig classe           # Ollama
bibliosig auteurs          # Ollama ; décisions manuelles lues dans data/
bibliosig graphe           # out/neo4j/*.csv et import.cypher
bibliosig analyses
bibliosig figures
bibliosig zotero --essai-a-blanc --filtre-sig --par-oeuvre
```

`python -m bibliosig …` équivaut à `bibliosig …`. `bibliosig tout` enchaîne les étapes
hors réseau, de la fusion aux figures.

### Mode `--rejouer`

Les étapes à modèle de langue (`dedoublonne --llm`, `classe`, `auteurs`) acceptent
`--rejouer` : au lieu d'interroger Ollama, elles rejouent les décisions enregistrées du
modèle de langue, relues dans les sorties existantes (`out/` ou `--decisions`). Les règles
déterministes (motifs, similarités, seuils) sont recalculées. Ce mode permet de refaire
toute la chaîne sans Ollama, à partir de décisions déjà prises.

```bash
bibliosig tout --rejouer
```

### Import dans Neo4j

`out/neo4j/` contient les nœuds et les relations en CSV et `import.cypher`. Copier les
CSV dans le dossier `import` de la base (Neo4j Desktop : « Open folder », « Import »),
puis exécuter `import.cypher` dans le navigateur de Neo4j. Les chemins
`file:///nodes_*.csv` du script désignent ce dossier `import` de Neo4j, pas un chemin
de votre ordinateur. `bibliosig graphe --importer` fait la même chose avec le pilote
officiel (option `[neo4j]`).

## Données à fournir

Aucune donnée n'est publiée dans ce dépôt, ni le graphe réel, ni ses extraits. Les
fichiers attendus, leurs colonnes et leur provenance sont décrits dans
[`data/README.md`](data/README.md) : collectes, fichier des corrections manuelles,
décisions manuelles sur les auteurs, paramètres nominatifs de la figure des co-auteurs.
Les tests utilisent seulement des notices fabriquées (`tests/donnees/`).

## Analyses

`bibliosig analyses` écrit dans `out/analyses/` :

- publications : notices par plateforme et par année, œuvres distinctes par année et par
  concept, part relative des mots-clés du bloc B, co-occurrences de concepts A et B. Les
  requêtes Cypher équivalentes sont dans
  [`requetes/publications_concepts.cypher`](requetes/publications_concepts.cypher), leurs
  équivalents Python dans `bibliosig.analyses.publications` ;
- flux des concepts A vers les concepts B (diagramme de Sankey) ;
- réseau des co-auteurs (communautés de Louvain ; les publications de plus de 30 auteurs
  n'ajoutent pas de liens) ;
- co-occurrences des mots des titres par année (option `--expressions-protegees` pour
  regrouper les synonymes de « SIG » et d'« analyse spatiale » avant les autres règles) ;
- `chiffres.json` : indicateurs résumés de ces tableaux.

Les paramètres sont dans `config/analyses.toml`. `bibliosig figures` dessine une image
simple par analyse dans `out/figures/`.

## Ouverture

Cette chaîne est un premier jet, qu'il conviendra d'étayer. Le réseau des co-auteurs en
est un exemple : les liens de co-signature sont des faits, mais leur regroupement en
communautés est une interprétation, qui varie d'une exécution à l'autre. Les noyaux sont
stables ; les frontières entre groupes voisins ne le sont pas. Comparer d'autres façons
de regrouper les personnes, et les discuter au regard de la littérature, reste à faire.

## Conditions d'utilisation des plateformes

La collecte interroge des services publics : respectez leurs conditions. Les pauses
entre requêtes, les délais et les nouvelles tentatives sont réglés dans
`config/plateformes.toml` ; toutes les requêtes portent la même signature,
`bibliosig/1.0.0 (+https://github.com/PigmentArcheo/GRAPHITE)`.

- HAL : API de recherche ouverte (CCSD), usage raisonnable demandé.
- OpenAlex : clé gratuite, limites de débit documentées par OpenAlex.
- Persée : archives RDF ouvertes de data.persee.fr ; téléchargement unique, réutilisé.
- SUDOC : service SRU de l'ABES (Agence bibliographique de l'enseignement supérieur).
- theses.fr : API publique de l'ABES.
- Frantiq : catalogue public ; une pause sépare chaque notice demandée.

## Bibliothèque Zotero

La bibliographie constituée avec cette chaîne est consultable dans la bibliothèque
publique du groupe PIGMENT : <https://www.zotero.org/groups/6617449/pigment_archeo>.

## Citation

Pour citer le logiciel, voir [`CITATION.cff`](CITATION.cff) (Laura Louman et Benoît
Pandolfi).

## Crédits

- Scripts de collecte de SUDOC, theses.fr et Frantiq : Laura Louman, reprise autorisée.
- Stratégies de similarité des titres : inspirées des travaux du consortium CRISalid
  (code consulté sur GitHub, non repris ici).

## Licence

MIT, voir [`LICENSE`](LICENSE).
