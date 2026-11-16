# Chaîne opératoire

Termes employés : une **notice** est une ligne fournie par une plateforme ; une
**œuvre** regroupe les notices d'une même publication (nœud `Work` du graphe) ; un
**concept** est un ensemble de termes ; un **couple** est une paire de concepts A × B.

## 1. Des concepts aux requêtes

```
config/concepts.toml
   bloc A : 10 concepts, 37 termes (19 mots français interrogés terme à terme)
   bloc B : 10 concepts, 24 termes (14 mots français, dont « apprentissage profond »)
        │
        ▼
couples A × B = 10 × 10 = 100
        │
        ├── « un OU par concept » : une requête par couple
        │      HAL       clause Solr (titre, mots-clés, résumé)   100 requêtes
        │      OpenAlex  deux filtres title_and_abstract.search    100 requêtes
        │      Persée    recherche locale dans les archives RDF   90 couples
        │                (cartographie/mapping et webSIG réunis)
        │
        └── « terme à terme puis rattachement » : une requête par paire de mots
               SUDOC     service SRU, tous champs                 266 paires
               theses.fr API de recherche                         266 paires
               Frantiq   catalogue Koha, puis notices MARC-XML    266 paires
               → chaque notice reçoit les couples de concepts de toutes les
                 paires qui l'ont trouvée (étape « normalise »)
```

Toutes les sorties portent le couple, sous la forme `libellé A × libellé B`, plusieurs
couples étant joints par ` || ` (colonne `AxB`).

## 2. Étapes

| Commande | Ce qu'elle fait | Entrées → sorties | Paramètres |
|---|---|---|---|
| `collecte` | Interroge les plateformes ; registre des notices et de leurs couples | réseau → `data/collecte/` | `config/plateformes.toml` |
| `normalise` | Schéma commun (12 colonnes), rattachement aux couples, `id_biblio` | `data/collecte/` → `data/<portail>_restructure.csv` | `[normalisation.*]` |
| `corrige` | Rejoue les retouches manuelles | `data/corrections_manuelles.csv` | — |
| `fusionne` | Concatène les six portails, sans supprimer de doublon | → `out/biblio_merged.csv` | `[fichiers]`, `[fusion]` |
| `filtre` | Passe négative : rejette le hors sujet évident sans signal archéologique. Passe positive : garde le vocabulaire archéologique ou un concept A strictement archéologique | → `biblio_p1*.csv`, `biblio_p2*.csv` | `config/filtres.toml` |
| `dedoublonne` | Même DOI ou même URI ; puis similarité des titres (n-grammes TF-IDF et rapidfuzz) ; avis facultatif de Mistral sur les paires de score intermédiaire | → `biblio_dedup.csv`, `biblio_annotated.csv`, `work_clusters.json` | `[dedoublonnage]` |
| `classe` | Pré-filtre SIG par motifs (confiance 0,95), puis Mistral pour les autres ; gardées si SIG et confiance ≥ 0,7, à relire sous 0,6 | → `biblio_sig.csv`, `biblio_sig_rejetes.csv`, `biblio_sig_a_relire.csv` | `[classification]`, `config/prompts/` |
| `auteurs` | Décisions manuelles, rapprochement dans une même œuvre, regroupement précoce, co-auteurs communs, familles de noms, arbitrage de Mistral, réintégration des alias | → `auteurs_clusters.csv`, `person_clusters.json`, `biblio_avec_persons.csv` | `[auteurs]` |
| `graphe` | Notices des œuvres SIG, personnes, concepts et couples ; `import.cypher` | → `out/neo4j/` | `[graphe]` |
| `analyses` | Tableaux et indicateurs : publications, concepts, flux, co-auteurs, mots des titres | → `out/analyses/` | `config/analyses.toml` |
| `figures` | Une image simple par analyse | → `out/figures/` | — |
| `zotero` | Envoi sans doublon (id_biblio lu dans le champ Extra) ; purge confirmée | CSV → bibliothèque Zotero | `[zotero]` |

Chaque étape écrit un bilan chiffré dans `out/bilans/<étape>.json`.

## 3. Modèle de langue et rejeu des décisions

Les appels à Mistral 7B passent par Ollama (`OLLAMA_URL`). Les prompts sont dans
`config/prompts/`. Avec `--rejouer` :

- `dedoublonne` : l'avis du modèle n'est pas demandé ; cet avis est seulement consigné
  et ne modifie pas les œuvres ;
- `classe` : le pré-filtre est recalculé, les autres décisions sont relues dans les trois
  sorties de la classification ; une notice rangée autrement que dans les sorties relues
  signale une retouche manuelle (comptée dans le bilan) ;
- `auteurs` : les décisions sont relues dans `auteurs_checkpoint.json` (une entrée par
  famille de noms) ; une famille absente est traitée comme une réponse illisible.

## 4. Retouches manuelles

Les retouches faites à la main (valeur d'une cellule modifiée, notice ajoutée, déplacée
ou retirée) sont décrites dans `data/corrections_manuelles.csv` et rejouées
automatiquement à la fin de l'étape qui produit chaque fichier visé. Le format est décrit dans [`data/README.md`](../data/README.md).
