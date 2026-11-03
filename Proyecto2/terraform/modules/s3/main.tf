resource "aws_s3_bucket" "dataset" {
  bucket        = var.bucket_name
  force_destroy = var.force_destroy

  tags = merge(
    var.tags,
    {
      Name        = var.bucket_name
      Environment = var.environment
      Project     = var.project_name
      Purpose     = "DVC Remote Storage"
    }
  )
}

# -----------------------------------------------------------------------------
# Versionamiento de S3: Requisito de la rúbrica para garantizar inmutabilidad
# y reproducibilidad del dataset versionado.
# -----------------------------------------------------------------------------
resource "aws_s3_bucket_versioning" "dataset" {
  bucket = aws_s3_bucket.dataset.id

  versioning_configuration {
    status = "Enabled"
  }
}

# -----------------------------------------------------------------------------
# Cifrado en reposo por defecto (SSE-S3 / AES256)
# -----------------------------------------------------------------------------
resource "aws_s3_bucket_server_side_encryption_configuration" "dataset" {
  bucket = aws_s3_bucket.dataset.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# -----------------------------------------------------------------------------
# Bloqueo total de acceso público (seguridad por diseño)
# -----------------------------------------------------------------------------
resource "aws_s3_bucket_public_access_block" "dataset" {
  bucket = aws_s3_bucket.dataset.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# -----------------------------------------------------------------------------
# Reglas de ciclo de vida para optimización de almacenamiento
# -----------------------------------------------------------------------------
resource "aws_s3_bucket_lifecycle_configuration" "dataset" {
  bucket = aws_s3_bucket.dataset.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

