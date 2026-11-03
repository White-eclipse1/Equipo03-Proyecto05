variable "bucket_name" {
  description = "Nombre del bucket S3 para almacenamiento de datasets y remote DVC"
  type        = string
}

variable "environment" {
  description = "Entorno de despliegue (prod, dev, staging)"
  type        = string
}

variable "project_name" {
  description = "Nombre del proyecto"
  type        = string
}

variable "force_destroy" {
  description = "Permitir eliminación del bucket incluso si contiene objetos (útil para pruebas, default false)"
  type        = bool
  default     = false
}

variable "tags" {
  description = "Etiquetas adicionales para el bucket"
  type        = map(string)
  default     = {}
}

