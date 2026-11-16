# Journal des versions

## 1.0.0

- Paquet Python `bibliosig` et commande du même nom, avec une sous-commande par étape.
- Collecte sur six plateformes : HAL, OpenAlex, Persée, SUDOC, theses.fr, Frantiq.
- Passage au schéma commun, rattachement des notices aux couples de concepts A × B.
- Retouches manuelles décrites dans un fichier de corrections, rejouées automatiquement.
- Fusion des portails, filtres thématiques négatif et positif, dédoublonnage en œuvres.
- Classification SIG (système d'information géographique) par motifs puis par modèle de
  langue (Mistral 7B via Ollama).
- Regroupement des formes de noms d'auteurs en personnes.
- Graphe Neo4j : fichiers CSV d'import, script `import.cypher` et import direct facultatif.
- Analyses : publications par plateforme, par année et par concept, co-occurrences de
  concepts, flux A vers B, réseau des co-auteurs, mots des titres.
- Figures simples (matplotlib) pour chaque analyse.
- Envoi des notices vers une bibliothèque Zotero, avec essai à blanc.
- Mode `--rejouer` : rejeu des décisions enregistrées du modèle de langue.
- Paramètres sortis du code, dans `config/` (concepts, motifs, seuils, modèle, prompts).
