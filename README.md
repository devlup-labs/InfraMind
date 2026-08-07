# InfraMind

**An AI-driven, self-healing Kubernetes observability agent.**

InfraMind watches a live Kubernetes workload, uses an LLM (Groq / Llama 3.3) to judge whether current metrics represent a real anomaly, investigates root cause from pod logs, and autonomously selects and executes a remediation action — restarting a pod, scaling the deployment, or rolling it back — before generating a human-readable incident report.

```
Prometheus metrics ──▶ Monitoring Agent (LLM) ──▶ anomaly?
                                                      │ yes
                                                      ▼
                                          Log Collector ──▶ Qdrant (vector store)
                                                      │
                                                      ▼
                                       Root Cause Agent (LLM + log search)
                                                      │
                                                      ▼
                              ┌────────── Optimization Agent (LLM, tool-calling) ──────────┐
                              │                                                             │
                     restart_pod tool                                          horizontal_pod_scaling tool
                              │                                                             │
                              └──────────────────────┬──────────────────────────────────────┘
                                                       ▼
                                          Wait & Recheck Metrics
                                          ├─ stabilized ──▶ Healthy End
                                          └─ retries exhausted ──▶ Rollback ──▶ Reporting Agent (LLM)
```

The pipeline is a [LangGraph](https://github.com/langchain-ai/langgraph) state machine (`agents/main.py`) orchestrating six cooperating LLM-backed agents plus a set of guarded Kubernetes tools.

---

## Table of contents

- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Running the pipeline](#running-the-pipeline)
- [Exercising each remediation tool](#exercising-each-remediation-tool)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Tearing down](#tearing-down)

---

## Architecture

| Component | File(s) | Role |
|---|---|---|
| Mock ML service | `app.py` | FastAPI app (DistilBERT sentiment) instrumented with Prometheus metrics — the workload being observed. |
| Monitoring Agent | `agents/monitoring_agent.py` | Pulls live Prometheus metrics, asks the LLM whether they represent an anomaly. |
| Log Collector | `agents/log_collector.py` | Pulls the affected pod's logs via `kubectl logs`. |
| Vector store | `agents/qdrant_manager.py`, `agents/embedding.py` | Embeds and stores logs in Qdrant for retrieval during root-cause analysis. |
| Root Cause Agent | `agents/root_cause_agent.py` | LLM analysis of retrieved logs against the flagged metric. |
| Optimization Agent | `agents/optimizing_agent.py` | LLM with **tool-calling** — picks `restart_pod` or `horizontal_pod_scaling` based on the root-cause narrative. |
| Remediation tools | `agents/tools.py` | Guarded Kubernetes actions: pod restart (with cooldown + circuit breaker), HPA apply, deployment rollback. |
| Rollback Agent | `agents/rollback_agent.py` | Escalation path when retries don't stabilize the workload. |
| Reporting Agent | `agents/reporting_agent.py` | LLM-generated incident report for the whole run. |
| Graph orchestration | `agents/main.py` | Wires all of the above into a LangGraph `StateGraph`. |

Supporting Kubernetes infra (in `k8s/`): the app `Deployment`/`Service`, `Prometheus` (Kubernetes-service-discovery scrape config + RBAC), `Qdrant`, and an RBAC role scoping what the restart agent may do. `agents/hpa.yaml` + `agents/values.yaml` wire up a `HorizontalPodAutoscaler` backed by `prometheus-adapter` custom metrics (`http_4xx_rate`, `http_5xx_rate`, `http_latency_p95_seconds`) plus standard CPU/memory utilization.

---

## Prerequisites

| Tool | Purpose | Install |
|---|---|---|
| **Docker** | Runs the local cluster and builds the app image | [docs.docker.com](https://docs.docker.com/get-docker/) |
| **kind** | Local Kubernetes cluster (Kubernetes-in-Docker) | `brew install kind` |
| **kubectl** | Talk to the cluster | `brew install kubectl` |
| **Helm** | Installs `prometheus-adapter` | `brew install helm` |
| **Python 3.10+** | Runs the agents | `brew install python@3.12` — the codebase uses `str \| None` syntax (PEP 604), so macOS's stock Python 3.9 **will not work**. |
| **Groq API key** | Powers every LLM call in the pipeline | Free tier at [console.groq.com](https://console.groq.com) |

---

## Quick start

```bash
git clone <this-repo-url>
cd InfraMind

# 1. Local Kubernetes cluster + namespace + RBAC
kind create cluster --name inframind
kubectl create namespace monitoring
kubectl apply -f k8s/restart-rbac.yaml

# 2. Build the app image and load it into the cluster
docker build -t inframind-model:latest .
kind load docker-image inframind-model:latest --name inframind

# 3. Deploy the app, Qdrant, and Prometheus
kubectl apply -f k8s/deployment.yaml -n monitoring
kubectl apply -f k8s/service.yaml -n monitoring
kubectl apply -f k8s/qdrant-deployment.yaml -n monitoring
kubectl apply -f k8s/prometheus.yaml -n monitoring
kubectl rollout status deployment/inframind-model-deployment -n monitoring
kubectl rollout status deployment/qdrant -n monitoring
kubectl rollout status deployment/prometheus-deployment -n monitoring

# 4. Wire up autoscaling (custom metrics + resource metrics)
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install prometheus-adapter prometheus-community/prometheus-adapter -n monitoring -f agents/values.yaml
kubectl rollout status deployment/prometheus-adapter -n monitoring

kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl patch deployment metrics-server -n kube-system --type='json' \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'

kubectl apply -f agents/hpa.yaml -n monitoring

# 5. Python environment for the agents
python3.12 -m venv .venv-agents
source .venv-agents/bin/activate
pip install -r requirements.txt

# 6. Configure secrets — see Configuration below
cp agents/.env.example agents/.env   # then fill in GROQ_API_KEY

# 7. Expose the cluster services to your machine (keep these running)
kubectl port-forward -n monitoring svc/inframind-model-service 8000:8000 &
kubectl port-forward -n monitoring svc/qdrant-service 6333:6333 &
kubectl port-forward -n monitoring svc/prometheus-service 9090:9090 &
```

Verify everything is reachable:
```bash
curl http://localhost:8000/health     # {"status": "healthy"}
curl http://localhost:9090/-/healthy  # Prometheus Server is Healthy.
curl http://localhost:6333/collections
```

---

## Configuration

All configuration lives in `agents/.env` (git-ignored — never commit real secrets):

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | **Yes** | — | Powers every LLM call (monitoring, root-cause, optimization, reporting). |
| `PROMETHEUS_URL` | No | `http://localhost:9090` | Where the monitoring agent queries metrics from. |
| `QDRANT_URL` | **Yes** | — | Qdrant endpoint for log storage/retrieval. |
| `QDRANT_COLLECTION` | **Yes** | — | Qdrant collection name (created automatically if missing). |
| `INFRAMIND_NAMESPACE` | No | `monitoring` | Namespace the remediation tools operate in. |
| `INFRAMIND_DEPLOYMENT` | No | `inframind-model-deployment` | Deployment name targeted by `rollback_deployment`. |
| `RESTART_COOLDOWN_SECONDS` | No | `60` | Minimum time between `restart_pod` actions. |
| `RESTART_MAX_PER_HOUR` | No | `6` | Circuit breaker: max restarts allowed per rolling hour. |
| `RESTART_MAX_RETRIES` | No | `2` | Optimization-loop retries before escalating to rollback. |
| `RESTART_WAIT_SECONDS` | No | `30` | Wait time between a mitigation attempt and re-checking metrics. |

Example `agents/.env`:
```bash
GROQ_API_KEY=gsk_your_key_here
PROMETHEUS_URL=http://localhost:9090
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=inframind_logs
INFRAMIND_NAMESPACE=monitoring
INFRAMIND_DEPLOYMENT=inframind-model-deployment
```

---

## Running the pipeline

The pipeline only *does* something when it detects an anomaly, so generate some traffic first. Two generators are provided, producing deliberately different anomaly shapes:

| Script | Traffic shape | Anomaly the monitoring agent sees | Remediation the optimization agent tends to pick |
|---|---|---|---|
| `Traffic_injector.py` | Malformed requests (404/405/422/500 mix) | Elevated `http_4xx_rate` / `http_5xx_rate` | `restart_pod` or `rollback_deployment` |
| `load_injector.py` | Sustained, valid, heavy `/predict` calls | High `cpu_usage_rate` / `http_latency_p95_seconds`, no errors | `horizontal_pod_scaling` |

**Never run both traffic generators at the same time** — the app is single-process, so combined load will queue up faster than it can drain.

```bash
# Terminal 1: pick ONE
TARGET_URL=http://localhost:8000 python3 Traffic_injector.py
# or
TARGET_URL=http://localhost:8000 LOAD_WORKERS=10 LOAD_DURATION_SECONDS=300 python3 load_injector.py

# Terminal 2: once metrics are visibly elevated, run the pipeline
cd agents
source ../.venv-agents/bin/activate
python3 main.py
```

Check the metrics are actually moving before running `main.py`:
```bash
curl -s --get 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=sum(rate(http_requests_total{job="fastapi_app",status=~"4xx|5xx"}[2m]))'
```

`main.py` prints the full trace: the raw metric snapshot, the anomaly verdict, the affected pod, root-cause analysis, every mitigation attempt and its result, the final status, and the generated incident report.

---

## Exercising each remediation tool

For a fast, deterministic check of a single tool against the **real** cluster (no LLM in the loop — this calls the tool functions directly and asserts on real cluster state):

```bash
source .venv-agents/bin/activate

python3 live_verification.py restart    # deletes a real pod, confirms it's replaced
python3 live_verification.py hpa        # floods real traffic, confirms replicas actually scale
python3 live_verification.py rollback   # forces a revision, rolls it back, confirms it reverted
python3 live_verification.py all        # runs all three, prints a PASS/FAIL summary
```

To see the LLM *choose* a tool on its own from a live anomaly (rather than calling it directly), use the traffic generators above and run `agents/main.py` — see [Running the pipeline](#running-the-pipeline).

---

## Testing

**Unit tests** — fast, mocked, no cluster required. Covers the guarded logic in `restart_pod` (cooldown, circuit breaker, exclusion labels):
```bash
source .venv-agents/bin/activate
python3 test.py -v
```

**Live integration tests** — see [Exercising each remediation tool](#exercising-each-remediation-tool) above.

---

## Project structure

```
InfraMind/
├── app.py                    # FastAPI mock ML service (the observed workload)
├── Traffic_injector.py       # Malformed-traffic generator (4xx/5xx anomaly)
├── load_injector.py          # Valid-traffic generator (CPU/latency anomaly)
├── live_verification.py      # Live integration checks against the real cluster
├── test.py                   # Mocked unit tests for the restart_pod tool
├── requirements.txt
├── Dockerfile                # Builds the app image
├── agents/
│   ├── main.py                # LangGraph pipeline definition
│   ├── monitoring_agent.py    # Metric fetch + LLM anomaly verdict
│   ├── log_collector.py       # kubectl logs wrapper
│   ├── qdrant_manager.py      # Vector store read/write
│   ├── embedding.py           # Sentence-transformer embeddings
│   ├── root_cause_agent.py    # LLM root-cause analysis
│   ├── optimizing_agent.py    # LLM tool-calling + mitigation loop
│   ├── rollback_agent.py      # Escalation path
│   ├── reporting_agent.py     # LLM incident report
│   ├── tools.py               # Guarded kubectl/K8s-API actions
│   ├── hpa.yaml                # HorizontalPodAutoscaler manifest
│   ├── values.yaml             # prometheus-adapter Helm values (custom metrics rules)
│   └── .env                   # Secrets (git-ignored, create this yourself)
└── k8s/
    ├── deployment.yaml         # App Deployment (with resource requests for HPA)
    ├── service.yaml            # App Service
    ├── qdrant-deployment.yaml  # Qdrant Deployment + Service
    ├── prometheus.yaml         # Prometheus Deployment + K8s-SD scrape config + RBAC
    └── restart-rbac.yaml       # RBAC for the restart agent's ServiceAccount
```

---

## Troubleshooting

- **`kubectl port-forward` keeps dying / app returns connection refused after a while.** This is expected — `port-forward` pins to one specific pod and dies the moment that pod is replaced (by a rollout, HPA scale event, or `restart_pod`). Just restart it: `kubectl port-forward -n monitoring svc/inframind-model-service 8000:8000 &`.
- **`cpu`/`memory` show `<unknown>` in `kubectl describe hpa`.** Either `metrics-server` isn't installed (see Quick start step 4), or the deployment's pod template lost its `resources.requests` (this happens if `rollback_deployment` reverts to a revision predating a manual infra change) — reapply: `kubectl apply -f k8s/deployment.yaml -n monitoring`.
- **`http_4xx_rate`/`http_5xx_rate` custom metrics show `<unknown>` with >1 replica.** `kubectl port-forward` only ever reaches *one* backing pod, so with multiple replicas the others report no data for that metric, and the HPA controller treats a missing per-pod value as an error rather than zero. This is a local-testing-harness limitation, not a bug — scale to a single replica for a clean demo: `kubectl scale deployment inframind-model-deployment -n monitoring --replicas=1`.
- **`ModuleNotFoundError: No module named 'requests'` (or similar).** You're running with system Python instead of the project venv. Activate it first: `source .venv-agents/bin/activate` (prompt should show `(.venv-agents)`).
- **`root_cause` / `incident_report` says "No ... was generated."** This is correct, not broken — `main.py` only proceeds past the monitoring stage if `anomaly_detected: true`. If metrics are flat, check that a traffic generator is actually running and reaching the app (`curl http://localhost:8000/health`).
- **Prometheus shows a lot of noisy/stale pod series after extended testing.** Prometheus here has no persistent volume, so a clean slate is one command away: `kubectl rollout restart deployment/prometheus-deployment -n monitoring`.

---

## Tearing down

```bash
pkill -f "kubectl port-forward"
kind delete cluster --name inframind
rm -rf .venv-agents
```
