variable "name" {
  description = "Name for the Lambda function, ECR repo, and SSM prefix."
  type        = string
  default     = "managed-agent-control-mcp"
}

variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
}

variable "image_tag" {
  description = "Tag of the container image (built from deploy/aws-lambda/Dockerfile) to deploy. Push it to the ECR repo this module creates, then apply with this tag."
  type        = string
}

variable "memory_mb" {
  description = "Lambda memory size (MB)."
  type        = number
  default     = 512
}

variable "timeout_seconds" {
  description = "Lambda timeout (s). Managed Agents control-plane calls are quick; 60s is comfortable."
  type        = number
  default     = 60
}

variable "log_retention_days" {
  description = "CloudWatch log retention (days)."
  type        = number
  default     = 30
}

variable "environment_variables" {
  description = "Non-secret config set as Lambda env vars (e.g. MCP_AUTH_MODE, MCP_OIDC_ISSUER, MCP_ALLOWED_AGENT_IDS). Secrets should go in SSM (see ssm_secret_keys), not here."
  type        = map(string)
  default     = {}
}

variable "ssm_secret_keys" {
  description = "Secret keys to provision as SSM SecureString placeholders under /<name>/. The Lambda loads them at cold start (uppercased: anthropic-api-key -> ANTHROPIC_API_KEY). Seed real values out-of-band with `aws ssm put-parameter --overwrite`; Terraform never stores the secret."
  type        = list(string)
  default     = ["anthropic-api-key"]
}

variable "create_function_url" {
  description = "Create a public Lambda Function URL (auth=NONE; the app enforces inbound auth itself)."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags merged onto every taggable resource."
  type        = map(string)
  default     = {}
}
