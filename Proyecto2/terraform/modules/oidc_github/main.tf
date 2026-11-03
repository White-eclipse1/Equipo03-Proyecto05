# -----------------------------------------------------------------------------
# Proveedor OIDC de GitHub Actions
# Permite autenticación federada sin almacenar claves estáticas en el repositorio,
# garantizando el cumplimiento estricto de la compuerta M2 (cero secretos).
# -----------------------------------------------------------------------------
data "tls_certificate" "github" {
  count = var.existing_oidc_provider_arn == "" ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
}

# Solo puede haber un proveedor OIDC por URL en cada cuenta. Si la cuenta ya lo
# tiene (otro proyecto lo creo), se reutiliza por ARN en vez de importarlo: un
# `terraform destroy` de este proyecto no debe borrarle el proveedor a otros.
resource "aws_iam_openid_connect_provider" "github" {
  count = var.existing_oidc_provider_arn == "" ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  thumbprint_list = distinct(concat(
    [data.tls_certificate.github[0].certificates[0].sha1_fingerprint],
    ["6938fd4d98bab03faadb97b34396831e3780aea1", "1c58a3a8518e8759bf075b76b750d4f8d264fcd9"]
  ))

  tags = merge(
    var.tags,
    {
      Name        = "github-actions-oidc-provider"
      Environment = var.environment
      Project     = var.project_name
    }
  )
}

moved {
  from = aws_iam_openid_connect_provider.github
  to   = aws_iam_openid_connect_provider.github[0]
}

locals {
  oidc_provider_arn = (
    var.existing_oidc_provider_arn != ""
    ? var.existing_oidc_provider_arn
    : aws_iam_openid_connect_provider.github[0].arn
  )
}

# -----------------------------------------------------------------------------
# Política de asunción de rol (Trust Policy)
# Solo permite asumir el rol a flujos de trabajo de GitHub Actions originados
# en el repositorio configurado.
# -----------------------------------------------------------------------------
data "aws_iam_policy_document" "github_actions_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # GitHub emite el `sub` en dos formatos segun tenga o no activada la
    # personalizacion del subject claim en el repositorio:
    #
    #   clasico: repo:<owner>/<repo>:ref:refs/heads/<rama>
    #   con IDs: repo:<owner>@<owner_id>/<repo>@<repo_id>:ref:refs/heads/<rama>
    #
    # El segundo existe para sobrevivir a un renombre del repo. Este repo lo
    # tiene activado, y como `StringLike` distingue mayusculas y no perdona un
    # caracter, el patron clasico por si solo rechazaba el token: CloudTrail
    # registraba AccessDenied contra
    # repo:stephy0410@121455794/ruta-al-dataset-v1@1364960219:ref:...
    #
    # Se aceptan los dos para que la config no dependa de como este esa opcion.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_repository}:*",
        format(
          "repo:%s@*/%s@*:*",
          split("/", var.github_repository)[0],
          split("/", var.github_repository)[1],
        ),
      ]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${var.project_name}-${var.environment}-github-actions-role"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume_role.json

  tags = merge(
    var.tags,
    {
      Name        = "${var.project_name}-${var.environment}-github-actions-role"
      Environment = var.environment
      Project     = var.project_name
      ManagedBy   = "Terraform"
    }
  )
}

# -----------------------------------------------------------------------------
# Política de privilegios mínimos para el remote DVC en S3
# Otorga únicamente ListBucket, GetObject, PutObject y DeleteObject.
# -----------------------------------------------------------------------------
data "aws_iam_policy_document" "dvc_s3_access" {
  statement {
    sid    = "ListDvcBucket"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation"
    ]
    resources = var.s3_bucket_arns
  }

  statement {
    sid    = "ReadWriteDvcObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]
    resources = [for arn in var.s3_bucket_arns : "${arn}/*"]
  }
}

resource "aws_iam_policy" "dvc_s3_access" {
  name        = "${var.project_name}-${var.environment}-dvc-s3-access"
  description = "Política de mínimos privilegios para el remote DVC sobre S3"
  policy      = data.aws_iam_policy_document.dvc_s3_access.json

  tags = merge(
    var.tags,
    {
      Environment = var.environment
      Project     = var.project_name
    }
  )
}

resource "aws_iam_role_policy_attachment" "github_actions_s3" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.dvc_s3_access.arn
}

