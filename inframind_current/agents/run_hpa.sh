#!/bin/bash
set -e

NAMESPACE="monitoring"
HPA_NAME="hpa-autoscaler"
DEPLOYMENT_NAME="inframind-model-deployment"

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts || true
helm repo update

helm upgrade --install prometheus-adapter prometheus-community/prometheus-adapter \
  -n ${NAMESPACE} \
  -f values.yaml

kubectl rollout status deployment/prometheus-adapter -n ${NAMESPACE} --timeout=120s

kubectl get apiservices | grep custom.metrics.k8s.io

kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" | python3 -m json.tool | grep '"name"'

echo ">> http_4xx_rate:"
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/${NAMESPACE}/pods/*/http_4xx_rate" || echo "no data yet"

echo ">> http_5xx_rate:"
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/${NAMESPACE}/pods/*/http_5xx_rate" || echo "no data yet"

echo ">> http_latency_p95_seconds:"
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/${NAMESPACE}/pods/*/http_latency_p95_seconds" || echo "no data yet"

kubectl apply -f hpa.yaml -n ${NAMESPACE}

kubectl get deployment ${DEPLOYMENT_NAME} -n ${NAMESPACE}

kubectl get hpa ${HPA_NAME} -n ${NAMESPACE} --watch