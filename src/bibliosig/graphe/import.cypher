// Import Neo4j — graphe bibliographique archéo/SIG
// Prérequis : les fichiers CSV doivent être dans le dossier 'import' de la DB
// Lancer ces commandes dans le Browser Neo4j

// 1. Contraintes d'unicité (obligatoire avant import)
CREATE CONSTRAINT portal_id      IF NOT EXISTS FOR (n:Portal)   REQUIRE n.nodeId IS UNIQUE;
CREATE CONSTRAINT record_id      IF NOT EXISTS FOR (n:Record)   REQUIRE n.id_biblio IS UNIQUE;
CREATE CONSTRAINT work_key       IF NOT EXISTS FOR (n:Work)     REQUIRE n.work_key IS UNIQUE;
CREATE CONSTRAINT author_key     IF NOT EXISTS FOR (n:Author)   REQUIRE n.author_key IS UNIQUE;
CREATE CONSTRAINT person_key     IF NOT EXISTS FOR (n:Person)   REQUIRE n.person_key IS UNIQUE;
CREATE CONSTRAINT conceptA_code  IF NOT EXISTS FOR (n:ConceptA) REQUIRE n.code IS UNIQUE;
CREATE CONSTRAINT conceptB_code  IF NOT EXISTS FOR (n:ConceptB) REQUIRE n.code IS UNIQUE;
CREATE CONSTRAINT pair_key       IF NOT EXISTS FOR (n:Pair)     REQUIRE n.pair_key IS UNIQUE;

// Index accessoires pour les recherches courantes
CREATE INDEX record_doi    IF NOT EXISTS FOR (n:Record) ON (n.doi);
CREATE INDEX record_year   IF NOT EXISTS FOR (n:Record) ON (n.year);
CREATE INDEX record_label  IF NOT EXISTS FOR (n:Record) ON (n.llm_label);
CREATE INDEX person_name   IF NOT EXISTS FOR (n:Person) ON (n.canonical_name);
CREATE INDEX work_title    IF NOT EXISTS FOR (n:Work)   ON (n.preferred_title);

// 2. Nœuds
LOAD CSV WITH HEADERS FROM 'file:///nodes_portals.csv' AS row
MERGE (p:Portal {nodeId: row.nodeId})
SET p.label = row.label;

LOAD CSV WITH HEADERS FROM 'file:///nodes_records.csv' AS row
MERGE (r:Record {id_biblio: row.id_biblio})
SET r.nodeId        = row.nodeId,
    r.id_portail    = row.id_portail,
    r.portail       = row.portail,
    r.titre         = row.titre,
    r.doi           = row.doi,
    r.uri           = row.uri,
    r.year          = toInteger(row.year),
    r.type          = row.type,
    r.resume        = row.resume,
    r.mots_cles     = row.mots_cles,
    r.llm_label     = row.llm_label,
    r.llm_confiance = toFloat(row.llm_confiance),
    r.llm_raison    = row.llm_raison;

LOAD CSV WITH HEADERS FROM 'file:///nodes_works.csv' AS row
MERGE (w:Work {work_key: row.work_key})
SET w.nodeId          = row.nodeId,
    w.preferred_title = row.preferred_title;

LOAD CSV WITH HEADERS FROM 'file:///nodes_authors.csv' AS row
MERGE (a:Author {author_key: row.author_key})
SET a.nodeId       = row.nodeId,
    a.display_name = row.display_name,
    a.portal       = row.portal;

LOAD CSV WITH HEADERS FROM 'file:///nodes_persons.csv' AS row
MERGE (p:Person {person_key: row.person_key})
SET p.nodeId         = row.nodeId,
    p.canonical_name = row.canonical_name;

LOAD CSV WITH HEADERS FROM 'file:///nodes_concepts_a.csv' AS row
MERGE (c:ConceptA {code: row.code})
SET c.nodeId = row.nodeId,
    c.label  = row.label;

LOAD CSV WITH HEADERS FROM 'file:///nodes_concepts_b.csv' AS row
MERGE (c:ConceptB {code: row.code})
SET c.nodeId = row.nodeId,
    c.label  = row.label;

LOAD CSV WITH HEADERS FROM 'file:///nodes_pairs.csv' AS row
MERGE (p:Pair {pair_key: row.pair_key})
SET p.nodeId = row.nodeId,
    p.label  = row.label;

// 3. Relations
// Portal -[HAS_RECORD]-> Record
LOAD CSV WITH HEADERS FROM 'file:///rels_has_record.csv' AS row
MATCH (p:Portal {nodeId: row.portal_id})
MATCH (r:Record {id_biblio: row.record_id})
MERGE (p)-[:HAS_RECORD]->(r);

// Record -[REPRESENTS]-> Work
LOAD CSV WITH HEADERS FROM 'file:///rels_represents.csv' AS row
MATCH (r:Record {id_biblio: row.record_id})
MATCH (w:Work {work_key: row.work_key})
MERGE (r)-[:REPRESENTS]->(w);

// Record -[AUTHORED_BY {rank}]-> Author
LOAD CSV WITH HEADERS FROM 'file:///rels_authored_by.csv' AS row
MATCH (r:Record {id_biblio: row.record_id})
MATCH (a:Author {author_key: row.author_key})
MERGE (r)-[rel:AUTHORED_BY]->(a)
SET rel.rank = toInteger(row.rank);

// Author -[IDENTIFIED_AS]-> Person
LOAD CSV WITH HEADERS FROM 'file:///rels_identified_as.csv' AS row
MATCH (a:Author {author_key: row.author_key})
MATCH (p:Person {person_key: row.person_key})
MERGE (a)-[:IDENTIFIED_AS]->(p);

// Record -[MATCHES_A]-> ConceptA
LOAD CSV WITH HEADERS FROM 'file:///rels_matches_a.csv' AS row
MATCH (r:Record {id_biblio: row.record_id})
MATCH (c:ConceptA {code: row.concept_code})
MERGE (r)-[:MATCHES_A]->(c);

// Record -[MATCHES_B]-> ConceptB
LOAD CSV WITH HEADERS FROM 'file:///rels_matches_b.csv' AS row
MATCH (r:Record {id_biblio: row.record_id})
MATCH (c:ConceptB {code: row.concept_code})
MERGE (r)-[:MATCHES_B]->(c);

// Record -[MATCHED_PAIR]-> Pair
LOAD CSV WITH HEADERS FROM 'file:///rels_matched_pair.csv' AS row
MATCH (r:Record {id_biblio: row.record_id})
MATCH (p:Pair {pair_key: row.pair_key})
MERGE (r)-[:MATCHED_PAIR]->(p);

// ConceptA -[IN_PAIR]-> Pair
LOAD CSV WITH HEADERS FROM 'file:///rels_in_pair_a.csv' AS row
MATCH (c:ConceptA {code: row.concept_code})
MATCH (p:Pair {pair_key: row.pair_key})
MERGE (c)-[:IN_PAIR]->(p);

// ConceptB -[IN_PAIR]-> Pair
LOAD CSV WITH HEADERS FROM 'file:///rels_in_pair_b.csv' AS row
MATCH (c:ConceptB {code: row.concept_code})
MATCH (p:Pair {pair_key: row.pair_key})
MERGE (c)-[:IN_PAIR]->(p);

// 4. Statistiques finales
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS nb ORDER BY nb DESC;
