output "oidc_provider_arn" {
  description = "ARN del proveedor IAM OIDC de GitHub Actions"
  value       = local.oidc_provider_arn
}

output "role_arn" {
  description = "ARN del rol de IAM para GitHub Actions"
  value       = aws_iam_role.github_actions.arn
}

output "role_name" {
  description = "Nombre del rol de IAM para GitHub Actions"
  value       = aws_iam_role.github_actions.name
}

output "policy_arn" {
  description = "ARN de la política IAM de acceso a S3 para DVC"
  value       = aws_iam_policy.dvc_s3_access.arn
}

