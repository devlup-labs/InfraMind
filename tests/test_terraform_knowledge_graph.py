import json
import tempfile
import unittest
from pathlib import Path

from agents.terraform_plan_parser import parse_plan_file
from agents.knowledge_graph.neo4j_client import Neo4jClient
from agents.knowledge_graph.terraform_ingestor import TerraformPlanIngestor

class TestTerraformKnowledgeGraph(unittest.TestCase):
    def test_end_to_end_flow(self):
        # 1. Define a mock Terraform JSON plan
        mock_plan = {
            "resource_changes": [
                {
                    "address": "kubernetes_deployment.inframind_model",
                    "type": "kubernetes_deployment",
                    "name": "inframind_model",
                    "provider_name": "registry.terraform.io/hashicorp/kubernetes",
                    "change": {
                        "actions": ["update"],
                        "before": {
                            "metadata": [{"name": "inframind-model-deployment", "namespace": "default"}]
                        },
                        "after": {
                            "metadata": [{"name": "inframind-model-deployment", "namespace": "default"}]
                        }
                    }
                }
            ]
        }

        # 2. Write to a temporary file and parse it
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "tfplan.json"
            file_path.write_text(json.dumps(mock_plan), encoding="utf-8")
            changes = parse_plan_file(file_path)

        # Verify parsed structure
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["address"], "kubernetes_deployment.inframind_model")
        self.assertEqual(changes[0]["actions"], ["update"])

        # 3. Ingest into the Neo4jClient (running in mock mode since environment variables aren't set)
        client = Neo4jClient()
        ingestor = TerraformPlanIngestor(client)
        ingestor.ingest("test-plan-123", changes)

        # 4. Assert nodes and relationships are created correctly
        # Verify TerraformPlan node
        self.assertTrue(any(n["label"] == "TerraformPlan" and n["identity"]["id"] == "test-plan-123" for n in client.nodes))
        
        # Verify TerraformResource node
        self.assertTrue(any(n["label"] == "TerraformResource" and n["identity"]["address"] == "kubernetes_deployment.inframind_model" for n in client.nodes))
        
        # Verify KubernetesResource node
        self.assertTrue(any(n["label"] == "KubernetesResource" and n["properties"]["kind"] == "Deployment" for n in client.nodes))

        # Verify relationships
        rel_types = [r["type"] for r in client.relationships]
        self.assertIn("PROPOSES_CHANGE_TO", rel_types)
        self.assertIn("MANAGES", rel_types)
        self.assertIn("BELONGS_TO", rel_types)

if __name__ == "__main__":
    unittest.main()
