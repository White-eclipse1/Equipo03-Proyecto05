# -----------------------------------------------------------------------------
# Acceso humano a los buckets del proyecto
# Un usuario IAM por integrante (lectura/escritura, misma politica que el rol de
# CI) y uno de solo lectura para el evaluador. Las llaves de acceso NO se crean
# aqui: `aws iam create-access-key` fuera de Terraform, para que el secreto
# nunca quede en el state.
# -----------------------------------------------------------------------------
resource "aws_iam_user" "team" {
  for_each = toset(var.team_members)

  name = "${var.project_name}-${each.key}"
  tags = merge(var.tags, { Role = "team" })
}

resource "aws_iam_user_policy_attachment" "team_rw" {
  for_each = aws_iam_user.team

  user       = each.value.name
  policy_arn = var.read_write_policy_arn
}

data "aws_iam_policy_document" "read_only" {
  statement {
    sid       = "ListBuckets"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:ListBucketVersions", "s3:GetBucketLocation"]
    resources = var.s3_bucket_arns
  }

  statement {
    sid       = "ReadObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = [for arn in var.s3_bucket_arns : "${arn}/*"]
  }
}

resource "aws_iam_policy" "read_only" {
  name        = "${var.project_name}-${var.environment}-s3-read-only"
  description = "Solo lectura sobre los buckets del proyecto (evaluador)"
  policy      = data.aws_iam_policy_document.read_only.json
  tags        = var.tags
}

resource "aws_iam_user" "evaluator" {
  count = var.create_evaluator ? 1 : 0

  name = "${var.project_name}-evaluator"
  tags = merge(var.tags, { Role = "evaluator" })
}

resource "aws_iam_user_policy_attachment" "evaluator_ro" {
  count = var.create_evaluator ? 1 : 0

  user       = aws_iam_user.evaluator[0].name
  policy_arn = aws_iam_policy.read_only.arn
}
