variable "namespace" {
  description = "Namespace containing the existing InfraMind model resources."
  type        = string
  default     = "default"
}

variable "deployment_name" {
  description = "Name of the existing InfraMind model Deployment."
  type        = string
  default     = "inframind-model-deployment"
}

variable "service_name" {
  description = "Name of the existing InfraMind model Service."
  type        = string
  default     = "inframind-model-service"
}

variable "image" {
  description = "Container image already available to the Minikube Docker driver."
  type        = string
  default     = "inframind-mock-model:v1"
}

variable "replicas" {
  description = "Desired number of model Deployment replicas."
  type        = number
  default     = 1
}

variable "cpu_request" {
  description = "CPU request for the model container."
  type        = string
  default     = "500m"
}

variable "memory_request" {
  description = "Memory request for the model container."
  type        = string
  default     = "700Mi"
}

variable "cpu_limit" {
  description = "CPU limit for the model container."
  type        = string
  default     = "1000m"
}

variable "memory_limit" {
  description = "Memory limit for the model container."
  type        = string
  default     = "1Gi"
}

variable "service_type" {
  description = "Kubernetes Service type for the existing model Service."
  type        = string
  default     = "NodePort"
}
