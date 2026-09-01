"""Map normalized Terraform plan changes to the initial Knowledge Graph model."""

from .neo4j_client import Neo4jClient
from .schema import (
    TERRAFORM_PLAN,
    TERRAFORM_RESOURCE,
    KUBERNETES_RESOURCE,
    NAMESPACE,
    PROPOSES_CHANGE_TO,
    MANAGES,
    BELONGS_TO,
)

def get_kubernetes_info(change):
    """Extract Kubernetes name, namespace, and kind if this is a Kubernetes resource."""
    res_type = change.get("resource_type") or ""
    if not res_type.startswith("kubernetes_"):
        return None

    # Try after, then fallback to before configuration block
    data = change.get("after") or change.get("before") or {}
    if not isinstance(data, dict):
        return None

    metadata = data.get("metadata")
    if isinstance(metadata, list) and metadata:
        metadata = metadata[0]
    
    if not isinstance(metadata, dict):
        return None

    name = metadata.get("name")
    if not name:
        return None

    namespace = metadata.get("namespace") or "default"
    # Convert 'kubernetes_deployment' to 'Deployment'
    kind = res_type.replace("kubernetes_", "").replace("_", " ").title().replace(" ", "")

    return {
        "kind": kind,
        "name": name,
        "namespace": namespace
    }

class TerraformPlanIngestor:
    """Ingests normalized Terraform changes into the Knowledge Graph."""
    def __init__(self, client: Neo4jClient):
        self.client = client

    def ingest(self, plan_id, changes):
        """Ingests a plan and its changes into Neo4j or mock in-memory client."""
        plan_identity = {"id": plan_id}
        self.client.upsert_node(TERRAFORM_PLAN, plan_identity, {})

        for change in changes:
            address = change.get("address")
            if not address:
                continue

            res_identity = {"address": address}
            res_props = {
                "type": change.get("resource_type"),
                "name": change.get("resource_name"),
                "provider_name": change.get("provider_name"),
                "actions": change.get("actions", [])
            }
            self.client.upsert_node(TERRAFORM_RESOURCE, res_identity, res_props)
            self.client.merge_relationship(TERRAFORM_PLAN, plan_identity, PROPOSES_CHANGE_TO, TERRAFORM_RESOURCE, res_identity)

            # Kubernetes specific node & relationship mapping
            k8s = get_kubernetes_info(change)
            if k8s:
                k8s_id = f"{k8s['namespace']}/{k8s['kind']}/{k8s['name']}"
                k8s_identity = {"id": k8s_id}
                self.client.upsert_node(KUBERNETES_RESOURCE, k8s_identity, k8s)
                self.client.merge_relationship(TERRAFORM_RESOURCE, res_identity, MANAGES, KUBERNETES_RESOURCE, k8s_identity)

                ns_identity = {"name": k8s["namespace"]}
                self.client.upsert_node(NAMESPACE, ns_identity, {})
                self.client.merge_relationship(KUBERNETES_RESOURCE, k8s_identity, BELONGS_TO, NAMESPACE, ns_identity)
