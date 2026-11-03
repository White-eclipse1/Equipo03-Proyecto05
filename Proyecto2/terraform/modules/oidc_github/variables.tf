variable "project_name" {
  description = "Nombre del proyecto"
  type        = string
}

variable "environment" {
  description = "Entorno de despliegue (prod, dev, staging)"
  type        = string
}

variable "github_repository" {
  description = "Repositorio de GitHub en formato 'owner/repo' autorizado para asumir el rol (ej: stephy0410/ruta-al-dataset-v1)"
  type        = string
}

variable "s3_bucket_arns" {
  description = "ARNs de los buckets S3 a los que el rol puede acceder (cache DVC y releases)"
  type        = list(string)
}

variable "tags" {
  description = "Etiquetas adicionales para los recursos IAM"
  type        = map(string)
  default     = {}
}


variable "existing_oidc_provider_arn" {
  description = "ARN de un proveedor OIDC de GitHub ya existente en la cuenta. Vacio = crearlo."
  type        = string
  default     = ""
}
