output "bucket_id" {
  description = "ID del bucket S3 creado"
  value       = aws_s3_bucket.dataset.id
}

output "bucket_arn" {
  description = "ARN del bucket S3 creado"
  value       = aws_s3_bucket.dataset.arn
}

output "bucket_name" {
  description = "Nombre del bucket S3 creado"
  value       = aws_s3_bucket.dataset.bucket
}

output "bucket_regional_domain_name" {
  description = "Nombre de dominio regional del bucket S3"
  value       = aws_s3_bucket.dataset.bucket_regional_domain_name
}

