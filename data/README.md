# Données attendues

Ce dossier reste hors Git (sauf ce fichier). Aucune donnée réelle n'est publiée : ni
les collectes, ni les sorties, ni le graphe, ni les décisions nominatives.

## 1. Collectes (`data/collecte/`)

Écrites par `bibliosig collecte`, lues par `bibliosig normalise`.

| Fichier ou dossier | Plateforme | Colonnes principales |
|---|---|---|
| `hal_matrix_dedup_100.csv` | HAL | `halId_s`, `combinaisons_AB`, `nb_combinaisons`, `doiId_s`, `title_s`, `authFullName_s`, `producedDateY_i`, `docType_s`, `keyword_s`, `abstract_s`, `uri_s` |
| `openalex_matrix_dedup.csv` | OpenAlex | `id`, `combinaisons_AB`, `doi`, `title`, `publication_year`, `type`, `primary_location.landing_page_url`, `authorships`, `keywords`, `abstract`… |
| `persee_matrix_dedup.csv`, `persee_index.csv`, `persee_dumps/` | Persée | `uri`, `combinaisons_AB`, `identifier`, `title`, `abstract`, `toc`, `date`, `authors`… |
| `resultats_sudoc_v6/*.csv` | SUDOC | un fichier par paire de mots (`mot__x__mot.csv`, point-virgule) : `PPN`, `Type`, `Auteurs`, `Titre`, `Annee`, `Mots-cles`, `Resume`, `URL`… ; `_RECAP.csv` |
| `results_theses/*.csv` | theses.fr | un fichier par paire (`mot_X_mot.csv`) : `titre`, `auteur`, `annee`, `mots_cles`, `resume_fr`, `nnt`, `url`… ; `_state.json` (reprise) |
| `resultats_frantiq/*.csv` | Frantiq | un fichier par paire : `Biblionumber`, `Type`, `Auteurs`, `Titre`, `Annee`, `Mots-cles_PACTOLS`, `Resume`, `URL`… |

À défaut des fichiers par paire, `normalise` accepte pour SUDOC, theses.fr et Frantiq un
fichier déjà rattaché aux couples, `<portail>_restructure_ok.csv` (schéma commun sans
`id_biblio`), et lui attribue ses identifiants.

## 2. Fichiers au schéma commun (`data/<portail>_restructure.csv`)

Écrits par `normalise`, lus par `fusionne`. Douze colonnes :

| Colonne | Contenu |
|---|---|
| `id_biblio` | préfixe du portail (HAL, OAL, PRS, SUD, THE, FRA) et numéro sur six chiffres |
| `portail` | HAL, OPENALEX, PERSEE, SUDOC, THESES, FRANTIQ |
| `id_portail` | identifiant propre à la plateforme |
| `DOI`, `uri` | identifiants de la publication |
| `auteurs` | formes de noms jointes par ` \|\| ` |
| `titre`, `resume`, `date`, `mots_cles`, `type` | métadonnées |
| `AxB` | couples de concepts « libellé A × libellé B », joints par ` \|\| ` |

## 3. Corrections manuelles (`data/corrections_manuelles.csv`)

Fichier de retouches manuelles de contenu, rejouées
automatiquement. Une ligne par opération :

| Colonne | Contenu |
|---|---|
| `fichier` | nom du fichier visé (par exemple `openalex_restructure.csv`, `biblio_sig.csv`) |
| `operation` | `modifier`, `ajouter`, `deplacer` ou `retirer` |
| `cle` | `id_biblio` de la ligne ; pour `auteurs_clusters.csv`, `auteur_raw` et `origine` joints par ` \| ` |
| `colonne`, `valeur` | cellule à fixer (`modifier`, `ajouter`) |
| `apres` | clé de la ligne après laquelle placer la ligne (`ajouter`, `deplacer`) |

Les opérations sont idempotentes. La fonction
`bibliosig.normalisation.corrections.deduire_corrections` produit ces lignes en
comparant un fichier produit par la chaîne et sa version retouchée.

## 4. Décisions manuelles sur les auteurs (`data/auteurs_clusters_corriges.csv`)

Lues par `bibliosig auteurs` (ou `--annotations`). Colonnes : `auteur_raw` (forme du
nom), `forme_retenue`, `confiance`, `raison`, `nb_refs`, `ids_biblio`,
`statut_annotation`, `cluster_id_final` (groupe décidé). Ce fichier contient des noms de
personnes et n'est pas publié.

## 5. Paramètres de la figure des co-auteurs (`data/figures/coauteurs.yaml`)

Corrections d'affichage des noms, noms à écrire, positions fixées à la main et groupes
des vues de détail. Format : `config/figures/coauteurs.exemple.yaml` (noms fictifs).
Lecture avec PyYAML (option `[figures]`).

## 6. Décisions déjà prises, pour le rejeu

`bibliosig classe --rejouer` relit `biblio_sig.csv`, `biblio_sig_rejetes.csv` et
`biblio_sig_a_relire.csv` (colonnes `id_biblio`, `llm_label`, `llm_confiance`,
`llm_raison`) ; `bibliosig auteurs --rejouer` relit `auteurs_checkpoint.json`
(`fam:<clé de famille>` vers la liste des groupes proposés par le modèle).
