"""Map normalized Terraform plan changes to the initial Knowledge Graph model."""

from .neo4j_client import Neo4jClient
from .schema import (
    TERRAFORM_PLAN,
    TERRAFORM_DEPLOYMENT,
    TERRAFORM_SERVICE,
    KUBERNETES_DEPLOYMENT,
    KUBERNETES_SERVICE,
    CONTAINER,
    CONTAINER_IMAGE,
    NAMESPACE,
    PROPOSES_CHANGE_TO,
    MANAGES,
    CONTAINS,
    USES,
    SELECTS,
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

def get_container_info(change):
    """Extract container name and image from a Kubernetes deployment."""
    if change.get("resource_type") != "kubernetes_deployment":
        return []

    data = change.get("after") or change.get("before") or {}
    if not isinstance(data, dict):
        return []

    spec = data.get("spec")
    if isinstance(spec, list) and spec:
        spec = spec[0]

    if not isinstance(spec, dict):
        return []

    template = spec.get("template")
    if isinstance(template, list) and template:
        template = template[0]

    if not isinstance(template, dict):
        return []

    pod_spec = template.get("spec")
    if isinstance(pod_spec, list) and pod_spec:
        pod_spec = pod_spec[0]

    if not isinstance(pod_spec, dict):
        return []

    containers = pod_spec.get("container", [])

    if not isinstance(containers, list):
        return []

    return [
        {
            "name": container.get("name"),
            "image": container.get("image"),
        }
        for container in containers
        if isinstance(container, dict) and container.get("name")
    ]

def get_selector_info(change):
    """Extract the selector labels from a Kubernetes resource."""
    data = change.get("after") or change.get("before") or {}

    if not isinstance(data, dict):
        return {}

    spec = data.get("spec")

    if isinstance(spec, list) and spec:
        spec = spec[0]

    if not isinstance(spec, dict):
        return {}

    selector = spec.get("selector")

    if isinstance(selector, list) and selector:
        selector = selector[0]

    if not isinstance(selector, dict):
        return {}

    match_labels = selector.get("match_labels")

    if isinstance(match_labels, dict):
        return match_labels

    return selector

def get_pod_labels(change):
    """Extract pod labels from a Kubernetes deployment."""
    if change.get("resource_type") != "kubernetes_deployment":
        return {}

    data = change.get("after") or change.get("before") or {}

    if not isinstance(data, dict):
        return {}

    spec = data.get("spec")

    if isinstance(spec, list) and spec:
        spec = spec[0]

    if not isinstance(spec, dict):
        return {}

    template = spec.get("template")

    if isinstance(template, list) and template:
        template = template[0]

    if not isinstance(template, dict):
        return {}

    metadata = template.get("metadata")

    if isinstance(metadata, list) and metadata:
        metadata = metadata[0]

    if not isinstance(metadata, dict):
        return {}

    labels = metadata.get("labels")

    return labels if isinstance(labels, dict) else {}

class TerraformPlanIngestor:
    """Ingests normalized Terraform changes into the Knowledge Graph."""
    def __init__(self, client: Neo4jClient):
        self.client = client

    def ingest(self, plan_id, changes):
        plan_identity = {"id": plan_id}
        self.client.upsert_node(TERRAFORM_PLAN, plan_identity, {})

        # first create all resource nodes
        resource_data = []

        for change in changes:
            address = change.get("address")
            resource_type = change.get("resource_type")

            if not address:
                continue

            if resource_type == "kubernetes_deployment":
                terraform_label = TERRAFORM_DEPLOYMENT
                kubernetes_label = KUBERNETES_DEPLOYMENT
            elif resource_type == "kubernetes_service":
                terraform_label = TERRAFORM_SERVICE
                kubernetes_label = KUBERNETES_SERVICE
            else:
                continue

            terraform_identity = {"address": address}

            terraform_properties = {
                "type": resource_type,
                "name": change.get("resource_name"),
                "provider_name": change.get("provider_name"),
                "actions": change.get("actions", [])
            }

            self.client.upsert_node(
                terraform_label,
                terraform_identity,
                terraform_properties
            )

            self.client.merge_relationship(
                TERRAFORM_PLAN,
                plan_identity,
                PROPOSES_CHANGE_TO,
                terraform_label,
                terraform_identity
            )

            k8s = get_kubernetes_info(change)

            if not k8s:
                continue

            k8s_id = f"{k8s['namespace']}/{k8s['kind']}/{k8s['name']}"
            k8s_identity = {"id": k8s_id}
            selector = get_selector_info(change)

            self.client.upsert_node(
                kubernetes_label,
                k8s_identity,
                {
                    **k8s,
                    "selector": selector
                }
            )

            self.client.merge_relationship(
                terraform_label,
                terraform_identity,
                MANAGES,
                kubernetes_label,
                k8s_identity
            )

            ns_identity = {"name": k8s["namespace"]}

            self.client.upsert_node(
                NAMESPACE,
                ns_identity,
                {}
            )

            self.client.merge_relationship(
                kubernetes_label,
                k8s_identity,
                BELONGS_TO,
                NAMESPACE,
                ns_identity
            )

            pod_labels = get_pod_labels(change)

            resource_data.append(
               (change, k8s, kubernetes_label, k8s_identity, pod_labels)
            )

        # connect services to deployments using selector labels
        for service_change, service_k8s, service_label, service_identity, service_labels in resource_data:
            if service_label != KUBERNETES_SERVICE:
                continue

            service_selector = get_selector_info(service_change)

            if not service_selector:
                continue

            for deployment_change, deployment_k8s, deployment_label, deployment_identity, deployment_labels in resource_data:
                if deployment_label != KUBERNETES_DEPLOYMENT:
                    continue

                if all(
                    deployment_labels.get(key) == value
                    for key, value in service_selector.items()
                ):
                    self.client.merge_relationship(
                        KUBERNETES_SERVICE,
                        service_identity,
                        SELECTS,
                        KUBERNETES_DEPLOYMENT,
                        deployment_identity
                    ) 

        # create deployment containers and images
        for change, k8s, kubernetes_label, k8s_identity, pod_labels in resource_data:
            if kubernetes_label != KUBERNETES_DEPLOYMENT:
                continue

            containers = get_container_info(change)

            for container in containers:
                if not container["name"]:
                    continue

                container_id = (
                    f"{k8s['namespace']}/"
                    f"{k8s['name']}/"
                    f"{container['name']}"
                )

                container_identity = {"id": container_id}

                self.client.upsert_node(
                    CONTAINER,
                    container_identity,
                    {
                        "name": container["name"]
                    }
                )

                self.client.merge_relationship(
                    KUBERNETES_DEPLOYMENT,
                    k8s_identity,
                    CONTAINS,
                    CONTAINER,
                    container_identity
                )

                if container["image"]:
                    image_identity = {"name": container["image"]}

                    self.client.upsert_node(
                        CONTAINER_IMAGE,
                        image_identity,
                        {}
                    )

                    self.client.merge_relationship(
                        CONTAINER,
                        container_identity,
                        USES,
                        CONTAINER_IMAGE,
                        image_identity
                    )