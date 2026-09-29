import os

K8S_NAMESPACE = os.getenv("INFRAMIND_NAMESPACE", "default")
K8S_DEPLOYMENT = os.getenv("INFRAMIND_DEPLOYMENT", "inframind-model-deployment")
CONFIGMAP_NAME = "inframind-app-config"
POD_LABEL_SELECTOR = "app=mock-model"