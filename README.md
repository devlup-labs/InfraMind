# Terraform & Knowledge Graph Integration Foundation

This directory contains the Terraform configuration for managing InfraMind's model Deployment and Service in the Kubernetes cluster.

## What is Terraform?
Terraform is an Infrastructure as Code (IaC) tool used to define, provision, and manage infrastructure in a declarative manner.

## Why is it used here?
In the context of InfraMind, Terraform allows the system to represent and reason about the **desired state** of the infrastructure, as opposed to the current runtime state. By comparing the desired state with the actual state and metrics, the future root cause analysis (RCA) and risk assessment agents can make informed optimization and self-healing decisions.

## Workflow

1. **Terraform Configuration**: Declare resources (`kubernetes_deployment` and `kubernetes_service`).
2. **Terraform Plan**: Run `terraform plan -out=tfplan` to compute proposed changes.
3. **JSON Representation**: Run `terraform show -json tfplan > tfplan.json` to generate a machine-readable representation.
4. **Plan Parser**: Run `python -m agents.terraform_plan_parser tfplan.json` to extract normalized changes.
5. **Knowledge Graph Ingestion**: Ingest the parsed plan into the Neo4j Knowledge Graph, creating nodes and relationships.

## Current Scope
This setup establishes the **data model and ingestion foundation** only. It does not perform autonomous remediation, plan verification, or automatic resource changes.

## Commands for Verification

To generate and parse a plan safely without modifying any resources:

```bash
# 1. Format and validate configuration
terraform fmt
terraform validate

# 2. Generate plan artifact
terraform plan -out=tfplan

# 3. Export to JSON
terraform show -json tfplan > tfplan.json

# 4. Parse JSON
python -m agents.terraform_plan_parser tfplan.json
```
