variable "aws_region" {
  description = "Región de AWS para desplegar la infraestructura"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Entorno de ejecución (prod, dev, staging)"
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Nombre base del proyecto"
  type        = string
  default     = "dataset-quality"
}

variable "vpc_cidr" {
  description = "Bloque CIDR para la VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Zonas de disponibilidad a utilizar"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "s3_bucket_name" {
  description = "Nombre único global para el bucket S3 del remote DVC"
  type        = string
  # Tiene que ser EXACTAMENTE la URL del remote `prod` de `.dvc/config`
  # (s3://dataset-quality-dvc-cache-750702272375). Si los dos nombres se separan,
  # `dvc push -r prod` apunta a un bucket que no existe y el fallo aparece
  # recien en CI, no aqui.
  default = "dataset-quality-dvc-cache-750702272375"
}

variable "s3_releases_bucket_name" {
  description = "Nombre único global para el bucket S3 de releases del dataset"
  type        = string
  default     = "dataset-quality-releases-750702272375"
}

variable "github_repository" {
  description = "Repositorio de GitHub en formato 'owner/repo' para la asunción del rol OIDC"
  type        = string
  default     = "sebastian0023/Proyecto-3-Clasificador-de-imagenes"
}

variable "tags" {
  description = "Etiquetas personalizadas para añadir a todos los recursos"
  type        = map(string)
  default     = {}
}


variable "existing_oidc_provider_arn" {
  description = "ARN del proveedor OIDC de GitHub si la cuenta ya tiene uno (solo puede existir uno por cuenta). Vacio = crearlo."
  type        = string
  default     = ""
}

variable "team_members" {
  description = "Integrantes del equipo con acceso de lectura/escritura a los buckets"
  type        = list(string)
  default     = []
}
