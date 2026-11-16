// Requêtes Cypher des publications par plateforme, par année et par concept.
// À exécuter dans Neo4j après l'import du graphe (étape « graphe »).
// Équivalents Python : module bibliosig.analyses.publications.

// Notices par plateforme et par année (1996 à 2025).
MATCH (portal:Portal)-[:HAS_RECORD]->(r:Record)
WHERE r.year IS NOT NULL
AND r.year >= 1996
AND r.year < 2026

RETURN
  portal.label AS portal,
  r.year AS year,
  count(*) AS nb_records

ORDER BY portal, year;

// Œuvres distinctes par concept (A ou B) et par année, à partir de 1996.
MATCH (r:Record)-[:REPRESENTS]->(w:Work)
MATCH (r)-[:MATCHES_A|MATCHES_B]->(c)
WHERE r.year IS NOT NULL
  AND r.year >= 1996
WITH DISTINCT w, c, r.year AS year
RETURN
  year,
  c.label AS concept,
  COUNT(DISTINCT w) AS nbWorks
ORDER BY year, nbWorks DESC;

// Co-occurrences concept A × concept B, en œuvres distinctes.
MATCH (r:Record)-[:REPRESENTS]->(w:Work)
MATCH (r)-[:MATCHES_A]->(ca:ConceptA)
MATCH (r)-[:MATCHES_B]->(cb:ConceptB)

RETURN
  ca.code AS conceptA,
  ca.label AS labelA,
  cb.code AS conceptB,
  cb.label AS labelB,
  count(DISTINCT w) AS weight

ORDER BY weight DESC;
