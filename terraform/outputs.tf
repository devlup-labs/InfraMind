output "deployment_identity" {
  description = "Terraform-managed InfraMind Deployment identity."
  value = {
    namespace = kubernetes_deployment.inframind_model.metadata[0].namespace
    name      = kubernetes_deployment.inframind_model.metadata[0].name
  }
}

output "service_identity" {
  description = "Terraform-managed InfraMind Service identity."
  value = {
    namespace = kubernetes_service.inframind_model.metadata[0].namespace
    name      = kubernetes_service.inframind_model.metadata[0].name
  }
}
