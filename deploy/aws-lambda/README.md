# AWS Lambda deployment

A self-contained Terraform module that runs **managed-agent-control-mcp** as a
container-image Lambda behind a public Function URL. It depends on no external
state and creates everything it needs: the ECR repo, the function, the execution
role, and SSM SecureString placeholders for secrets.

> [!NOTE]
> This is a minimal, focused module. CloudFront/CDN, custom domains, and Cognito
> user-pool creation are intentionally out of scope — front the Function URL with
> your own CDN/domain if you need them. The app supports bearer/OIDC/Cognito auth
> regardless (configure via `environment_variables` + SSM).

## Usage

```hcl
module "mcp" {
  source     = "github.com/modus-agendi/managed-agent-control-mcp//deploy/aws-lambda"
  aws_region = "eu-central-1"
  image_tag  = "v0.1.0"

  # Non-secret config as Lambda env vars. Secrets go in SSM (see below).
  environment_variables = {
    MCP_AUTH_MODE = "bearer"
  }

  # Placeholders created in SSM; seed the real values out-of-band.
  ssm_secret_keys = ["anthropic-api-key", "mcp-bearer-token"]
}
```

## Deploy steps

```bash
cd deploy/aws-lambda
terraform init

# 1. First apply creates the ECR repo (image_tag can be anything for now).
terraform apply -var aws_region=eu-central-1 -var image_tag=bootstrap

# 2. Build + push the image to the new repo.
ECR=$(terraform output -raw ecr_repository_url)
aws ecr get-login-password --region eu-central-1 \
  | docker login --username AWS --password-stdin "${ECR%/*}"
docker build -f ../../deploy/aws-lambda/Dockerfile -t "$ECR:v0.1.0" ../..
docker push "$ECR:v0.1.0"

# 3. Apply with the real tag to point the function at the image.
terraform apply -var aws_region=eu-central-1 -var image_tag=v0.1.0

# 4. Seed secrets (never stored in Terraform state).
aws ssm put-parameter --type SecureString --overwrite \
  --name "$(terraform output -raw ssm_param_prefix)anthropic-api-key" \
  --value 'sk-ant-...' --region eu-central-1

# 5. Connect: the MCP endpoint is <function_url>mcp.
terraform output function_url
```

## Inputs

| Variable | Default | Description |
|---|---|---|
| `aws_region` | — (required) | Region to deploy into. |
| `image_tag` | — (required) | Container image tag to run. |
| `name` | `managed-agent-control-mcp` | Function / ECR / SSM-prefix name. |
| `memory_mb` | `512` | Lambda memory. |
| `timeout_seconds` | `60` | Lambda timeout. |
| `log_retention_days` | `30` | CloudWatch retention. |
| `environment_variables` | `{}` | Non-secret env config (e.g. `MCP_AUTH_MODE`). |
| `ssm_secret_keys` | `["anthropic-api-key"]` | Secret keys provisioned as SSM placeholders. |
| `create_function_url` | `true` | Create a public Function URL. |
| `tags` | `{}` | Resource tags. |

Secrets in SSM are loaded into the Lambda environment at cold start, uppercased
with `-`/`/` → `_` (so `anthropic-api-key` → `ANTHROPIC_API_KEY`,
`mcp-bearer-token` → `MCP_BEARER_TOKEN`).
