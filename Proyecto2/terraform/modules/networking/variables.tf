variable "project_name" {
  description = "Nombre del proyecto para prefijar recursos y etiquetas"
  type        = string
}

variable "environment" {
  description = "Entorno de despliegue (prod, dev, staging)"
  type        = string
}

variable "vpc_cidr" {
  description = "Bloque CIDR de la VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Zonas de disponibilidad para subredes"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "public_subnet_cidrs" {
  description = "Bloques CIDR para subredes públicas"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "Bloques CIDR para subredes privadas"
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.20.0/24"]
}

variable "tags" {
  description = "Etiquetas adicionales para los recursos"
  type        = map(string)
  default     = {}
}

