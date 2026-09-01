"""A clean, simple Neo4j client that falls back to an in-memory mock for local testing."""

import os

class Neo4jClient:
    """A clean, simple Neo4j client that falls back to an in-memory mock for local testing."""
    def __init__(self):
        self.uri = os.environ.get("NEO4J_URI")
        self.username = os.environ.get("NEO4J_USERNAME")
        self.password = os.environ.get("NEO4J_PASSWORD")
        self.driver = None

        if self.uri and self.username and self.password:
            try:
                from neo4j import GraphDatabase
                self.driver = GraphDatabase.driver(self.uri, auth=(self.username, self.password))
            except ImportError:
                pass

        if not self.driver:
            # Fallback to simple in-memory storage for testing
            self.nodes = []
            self.relationships = []

    def upsert_node(self, label, identity, properties):
        """Insert or update a node identified by label and identity properties."""
        if self.driver:
            # Get the first key and value of identity to match on
            id_key = list(identity.keys())[0]
            id_val = identity[id_key]
            all_props = {**identity, **properties}
            query = f"MERGE (n:{label} {{{id_key}: $id_val}}) SET n += $all_props"
            with self.driver.session() as session:
                session.run(query, id_val=id_val, all_props=all_props)
        else:
            record = {"label": label, "identity": dict(identity), "properties": dict(properties)}
            self.nodes = [n for n in self.nodes if not (n["label"] == label and n["identity"] == record["identity"])]
            self.nodes.append(record)

    def merge_relationship(self, source_label, source_identity, relationship, target_label, target_identity, properties=None):
        """Create a directed relationship between two nodes."""
        if self.driver:
            src_key = list(source_identity.keys())[0]
            src_val = source_identity[src_key]
            tgt_key = list(target_identity.keys())[0]
            tgt_val = target_identity[tgt_key]
            query = (
                f"MATCH (src:{source_label} {{{src_key}: $src_val}}) "
                f"MATCH (tgt:{target_label} {{{tgt_key}: $tgt_val}}) "
                f"MERGE (src)-[r:{relationship}]->(tgt) "
                f"SET r += $properties"
            )
            with self.driver.session() as session:
                session.run(query, src_val=src_val, tgt_val=tgt_val, properties=dict(properties or {}))
        else:
            self.relationships.append({
                "source_label": source_label,
                "source_identity": dict(source_identity),
                "type": relationship,
                "target_label": target_label,
                "target_identity": dict(target_identity),
                "properties": dict(properties or {})
            })
