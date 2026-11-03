output "team_user_names" {
  description = "Usuarios IAM de lectura/escritura"
  value       = [for u in aws_iam_user.team : u.name]
}

output "evaluator_user_name" {
  description = "Usuario IAM de solo lectura para el evaluador"
  value       = try(aws_iam_user.evaluator[0].name, null)
}
