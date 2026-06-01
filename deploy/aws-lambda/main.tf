# Self-contained AWS Lambda deployment for managed-agent-control-mcp.
#
# Creates everything it needs and depends on NO external/remote Terraform state:
#   - an ECR repository to hold the container image
#   - the Lambda function (container image) + a public Function URL
#   - an execution role scoped to CloudWatch Logs + reading this server's SSM secrets
#   - SSM SecureString placeholders for secrets (seed the values out-of-band)
#
# Out of scope for this minimal module (front the Function URL yourself if you
# need them): CloudFront/CDN, custom domains, and creating a Cognito user pool.
# The app already supports OIDC/Cognito auth via env vars / SSM.

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  ssm_prefix = "/${var.name}/"
  ssm_arn_glob = format(
    "arn:aws:ssm:%s:%s:parameter%s*",
    data.aws_region.current.name,
    data.aws_caller_identity.current.account_id,
    local.ssm_prefix,
  )
}

# ---- container registry ------------------------------------------------------

resource "aws_ecr_repository" "this" {
  name                 = var.name
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = var.tags
}

# ---- secrets (placeholders; seed real values out-of-band) --------------------

resource "aws_ssm_parameter" "secret" {
  for_each = toset(var.ssm_secret_keys)

  name  = "${local.ssm_prefix}${each.value}"
  type  = "SecureString"
  value = "REPLACE_ME" # overwrite out-of-band; Terraform ignores drift below.

  lifecycle {
    ignore_changes = [value]
  }

  tags = var.tags
}

# ---- execution role ----------------------------------------------------------

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }

  statement {
    sid       = "ReadSecrets"
    actions   = ["ssm:GetParametersByPath", "ssm:GetParameter", "ssm:GetParameters"]
    resources = [local.ssm_arn_glob]
  }

  # SecureString decrypt via the default SSM KMS key, scoped to SSM usage only.
  statement {
    sid       = "DecryptSecrets"
    actions   = ["kms:Decrypt"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${data.aws_region.current.name}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${var.name}-policy"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

# ---- function ----------------------------------------------------------------

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_lambda_function" "this" {
  function_name = var.name
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.this.repository_url}:${var.image_tag}"
  memory_size   = var.memory_mb
  timeout       = var.timeout_seconds

  environment {
    # SSM_PARAM_PREFIX drives the cold-start secret loader (app/ssm.py). Merge
    # in any non-secret config the operator passes.
    variables = merge(var.environment_variables, { SSM_PARAM_PREFIX = local.ssm_prefix })
  }

  depends_on = [aws_iam_role_policy.lambda, aws_cloudwatch_log_group.lambda]
  tags       = var.tags
}

resource "aws_lambda_function_url" "this" {
  count              = var.create_function_url ? 1 : 0
  function_name      = aws_lambda_function.this.function_name
  authorization_type = "NONE" # the MCP app enforces inbound auth (bearer/OIDC/Cognito)
}
