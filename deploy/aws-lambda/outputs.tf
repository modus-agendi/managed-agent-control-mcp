output "function_url" {
  description = "Public HTTPS endpoint for the Lambda Function URL. The MCP endpoint is <url>mcp. Send Authorization: Bearer <token> (or complete the OAuth flow)."
  value       = try(aws_lambda_function_url.this[0].function_url, null)
}

output "function_name" {
  description = "Lambda function name."
  value       = aws_lambda_function.this.function_name
}

output "ecr_repository_url" {
  description = "ECR repository to push the container image to (tag it with var.image_tag)."
  value       = aws_ecr_repository.this.repository_url
}

output "ssm_param_prefix" {
  description = "SSM prefix holding secrets. Seed values, e.g.: aws ssm put-parameter --name <prefix>anthropic-api-key --type SecureString --overwrite --value sk-ant-..."
  value       = local.ssm_prefix
}

output "role_arn" {
  description = "Lambda execution role ARN."
  value       = aws_iam_role.lambda.arn
}
