# =============================================================================
# Infraestructura Proyecto 2: Calidad y Versionado de Datasets
# Orquestación de módulos: Red + S3 Gateway Endpoint, S3 Storage y OIDC IAM.
# =============================================================================

module "networking" {
  source = "./modules/networking"

  project_name       = var.project_name
  environment        = var.environment
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
  tags               = var.tags
}

module "s3" {
  source = "./modules/s3"

  bucket_name  = var.s3_bucket_name
  environment  = var.environment
  project_name = var.project_name
  tags         = var.tags
}

# Segundo bucket: los releases (`dataset.tar.zst` de cada version) no comparten
# bucket con el cache de DVC. Son ciclos de vida distintos -- el cache es
# contenido direccionable por hash que se puede regenerar, un release es un
# artefacto inmutable que se publica -- y mezclarlos hace que una regla de
# lifecycle pensada para uno afecte al otro.
module "s3_releases" {
  source = "./modules/s3"

  bucket_name  = var.s3_releases_bucket_name
  environment  = var.environment
  project_name = var.project_name
  tags         = var.tags
}

module "oidc_github" {
  source = "./modules/oidc_github"

  project_name      = var.project_name
  environment       = var.environment
  github_repository = var.github_repository

  existing_oidc_provider_arn = var.existing_oidc_provider_arn
  # El rol necesita los dos buckets: `dvc pull` lee del cache y `dq release`
  # publica el artefacto de la version.
  s3_bucket_arns = [
    module.s3.bucket_arn,
    module.s3_releases.bucket_arn,
  ]
  tags = var.tags
}


# Acceso de las personas: un usuario por integrante y uno de solo lectura para
# el evaluador (criterio 5.2 de la rubrica del P3).
module "team_access" {
  source = "./modules/team_access"

  project_name          = var.project_name
  environment           = var.environment
  team_members          = var.team_members
  read_write_policy_arn = module.oidc_github.policy_arn
  s3_bucket_arns = [
    module.s3.bucket_arn,
    module.s3_releases.bucket_arn,
  ]
  tags = var.tags
}
