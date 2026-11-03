output "vpc_id" {
  description = "ID de la VPC principal"
  value       = module.networking.vpc_id
}

output "s3_vpc_endpoint_id" {
  description = "ID del Gateway VPC Endpoint para S3"
  value       = module.networking.s3_endpoint_id
}

output "public_subnet_ids" {
  description = "IDs de las subredes públicas"
  value       = module.networking.public_subnet_ids
}

output "private_subnet_ids" {
  description = "IDs de las subredes privadas"
  value       = module.networking.private_subnet_ids
}

output "s3_bucket_name" {
  description = "Nombre del bucket S3 para el remote DVC en producción"
  value       = module.s3.bucket_name
}

output "s3_bucket_arn" {
  description = "ARN del bucket S3 para el remote DVC en producción"
  value       = module.s3.bucket_arn
}

output "github_actions_role_arn" {
  description = "ARN del rol de IAM asumible por GitHub Actions vía OIDC (cero llaves estáticas)"
  value       = module.oidc_github.role_arn
}

output "github_actions_role_name" {
  description = "Nombre del rol de IAM para GitHub Actions"
  value       = module.oidc_github.role_name
}

output "oidc_provider_arn" {
  description = "ARN del proveedor IAM OIDC de GitHub"
  value       = module.oidc_github.oidc_provider_arn
}


output "s3_releases_bucket_name" {
  description = "Nombre del bucket S3 de releases del dataset"
  value       = module.s3_releases.bucket_name
}

output "s3_releases_bucket_arn" {
  description = "ARN del bucket S3 de releases del dataset"
  value       = module.s3_releases.bucket_arn
}

output "team_user_names" {
  description = "Usuarios IAM de lectura/escritura del equipo"
  value       = module.team_access.team_user_names
}

output "evaluator_user_name" {
  description = "Usuario IAM de solo lectura para el evaluador"
  value       = module.team_access.evaluator_user_name
}
