provider "kubernetes" {
  config_path = "~/.kube/config"
}

resource "kubernetes_deployment" "inframind_model" {
  metadata {
    name = "inframind-model-deployment"
  }

  spec {
    replicas = 1

    selector {
      match_labels = {
        app = "mock-model"
      }
    }

    template {
      metadata {
        labels = {
          app = "mock-model"
        }

        annotations = {
          "prometheus.io/scrape" = "true"
          "prometheus.io/path"   = "/metrics"
          "prometheus.io/port"   = "8000"
        }
      }

      spec {
        automount_service_account_token = false
        enable_service_links            = false

        container {
          name  = "fastapimodel"
          image = "inframind-mock-model:v1"

          image_pull_policy = "Never"

          port {
            container_port = 8000
          }

          env {
            name  = "PROMETHEUS_URL"
            value = "http://prometheus-service.default.svc.cluster.local:9090"
          }

          env {
            name  = "QDRANT_URL"
            value = "http://qdrant-service.default.svc.cluster.local:6333"
          }

          env {
            name  = "QDRANT_COLLECTION"
            value = "inframind_logs"
          }

          env {
            name  = "GROQ_API_KEY"
            value = "GROQ_API_KEY"
          }

          env {
            name  = "INFRAMIND_NAMESPACE"
            value = "monitoring"
          }

          env {
            name  = "INFRAMIND_DEPLOYMENT"
            value = "inframind-model-deployment"
          }

          env {
            name  = "RESTART_COOLDOWN_SECONDS"
            value = "60"
          }

          env {
            name  = "RESTART_MAX_PER_HOUR"
            value = "6"
          }

          env {
            name  = "RESTART_MAX_RETRIES"
            value = "2"
          }

          env {
            name  = "RESTART_WAIT_SECONDS"
            value = "30"
          }

          resources {
            requests = {
              cpu    = "500m"
              memory = "700Mi"
            }

            limits = {
              cpu    = "1000m"
              memory = "1Gi"
            }
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "inframind_model" {
  metadata {
    name = "inframind-model-service"

    annotations = {
      "prometheus.io/scrape" = "true"
      "prometheus.io/port"   = "8000"
      "prometheus.io/path"   = "/metrics"
    }
  }

  spec {
    type = "NodePort"

    selector = {
      app = "mock-model"
    }

    port {
      port        = 8000
      target_port = 8000
    }
  }
}
