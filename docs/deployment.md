# Deployment

Three targets, one codebase. The same `build_app` ASGI shape backs both HTTP
targets, so behavior is identical across container and Lambda.

## Local (stdio)

For personal use, Claude Code, and the MCP Inspector. No inbound auth (no network
boundary).

```bash
uv sync
ANTHROPIC_API_KEY=sk-ant-... uv run python -m managed_agents_mcp
```

## Generic container (HTTP)

For Fly.io, Render, Google Cloud Run, AWS ECS/Fargate, or a VPS. Serves the
streamable-HTTP transport with uvicorn on port 8000.

```bash
docker build -f deploy/Dockerfile -t managed-agent-control-mcp .

docker run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e MCP_AUTH_MODE=bearer \
  -e MCP_BEARER_TOKEN="$(openssl rand -hex 32)" \
  managed-agent-control-mcp
```

The MCP endpoint is `http://<host>:8000/mcp`. Put it behind TLS (a reverse proxy
or your platform's HTTPS) before exposing it. Set `MCP_PUBLIC_URL` if a proxy or
custom domain fronts it so OAuth discovery advertises the right URL.

> [!WARNING]
> Set `MCP_AUTH_MODE` for HTTP. Without it the server **refuses to start** (no
> inbound auth means anyone who reaches it can drive your key). To run without
> auth anyway — `localhost` / trusted private networks only — set
> `MCP_ALLOW_INSECURE_NO_AUTH=true`.

## AWS Lambda

A self-contained Terraform module (no external/remote state) in
[`deploy/aws-lambda/`](../deploy/aws-lambda/) creates the ECR repo, the Lambda
(container image) + Function URL, the execution role, and SSM SecureString
placeholders for secrets.

```bash
cd deploy/aws-lambda
terraform init
terraform apply -var aws_region=eu-central-1 -var image_tag=bootstrap   # creates ECR

ECR=$(terraform output -raw ecr_repository_url)
aws ecr get-login-password --region eu-central-1 \
  | docker login --username AWS --password-stdin "${ECR%/*}"
docker build -f deploy/aws-lambda/Dockerfile -t "$ECR:v0.1.0" ../..
docker push "$ECR:v0.1.0"

terraform apply -var aws_region=eu-central-1 -var image_tag=v0.1.0

# Seed secrets (never stored in Terraform state):
aws ssm put-parameter --type SecureString --overwrite --region eu-central-1 \
  --name "$(terraform output -raw ssm_param_prefix)anthropic-api-key" --value 'sk-ant-...'
```

The MCP endpoint is `<function_url>mcp`. See the module's
[README](../deploy/aws-lambda/README.md) for inputs and the CloudFront/custom-domain
note.

## Hardening notes

- **No built-in rate limiting.** Authentication gates *who* can call the server, but
  any authenticated caller (or a leaked token) can create sessions and burn tokens
  without an application-level cap. Front the HTTP/Lambda endpoint with a reverse
  proxy / API gateway / WAF rate limit, and rotate inbound credentials if you suspect
  abuse. On Lambda, `reserved_concurrency` (default 5) bounds the concurrent blast
  radius; container/VPS deploys have no equivalent unless you add one.
- **Bound and detect.** The optional guardrails (`MCP_ALLOWLIST_AGENTS_ACTIVE` +
  `MCP_ALLOWED_AGENT_IDS`, `MCP_ALLOWED_ENVIRONMENT_IDS`, `MCP_ALLOW_DESTRUCTIVE`)
  limit what a caller can do, and every session-affecting tool emits a one-line
  `"audit"` JSON record to **stderr** — alarm on its volume to catch a leaked
  credential spawning agents.

## Releasing (PyPI + GHCR)

Tagging a SemVer release runs `.github/workflows/release.yml`, which publishes to
PyPI (Trusted Publishing / OIDC — configure the publisher on PyPI first) and
pushes a container image to GHCR:

```bash
git tag v0.1.0 && git push origin v0.1.0
```
