variable "project_name" {
  description = "Nombre del proyecto (prefijo de los usuarios IAM)"
  type        = string
}

variable "environment" {
  description = "Entorno de despliegue (prod, dev, staging)"
  type        = string
}

variable "team_members" {
  description = "Integrantes con acceso de lectura/escritura (un usuario IAM cada uno)"
  type        = list(string)
}

variable "create_evaluator" {
  description = "Crear el usuario de solo lectura para el evaluador"
  type        = bool
  default     = true
}

variable "read_write_policy_arn" {
  description = "ARN de la politica de lectura/escritura sobre los buckets"
  type        = string
}

variable "s3_bucket_arns" {
  description = "ARNs de los buckets a los que da acceso de lectura el evaluador"
  type        = list(string)
}

variable "tags" {
  description = "Etiquetas adicionales"
  type        = map(string)
  default     = {}
}
