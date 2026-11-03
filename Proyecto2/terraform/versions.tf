terraform {
  # 1.10 es donde aparece `use_lockfile`, el bloqueo nativo del backend S3.
  # Antes hacia falta una tabla de DynamoDB solo para el lock; ya no.
  required_version = ">= 1.10.0"

  # Estado remoto. Con el state en local, cada quien aplicaba contra su propia
  # copia: asi fue como los recursos de IAM acabaron creados por una maquina y
  # ausentes del state de otra, y hubo que importarlos a mano. El bucket se
  # crea FUERA de Terraform a proposito -- no puede gestionarse a si mismo:
  #   aws s3api create-bucket --bucket dataset-quality-tfstate-prod --region us-east-1
  #   aws s3api put-bucket-versioning --bucket ... --versioning-configuration Status=Enabled
  # El versionado del bucket es la red de seguridad: permite recuperar un
  # state anterior si un apply lo corrompe.
  backend "s3" {
    bucket       = "dataset-quality-tfstate-prod"
    key          = "prod/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

