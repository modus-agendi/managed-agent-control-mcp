# Generic HTTP container — runs the MCP server over streamable-HTTP with uvicorn.
# Suitable for any host: Fly.io, Render, Google Cloud Run, AWS ECS/Fargate, a VPS.
# (For AWS Lambda use deploy/aws-lambda/Dockerfile instead.)
#
#   docker build -f deploy/Dockerfile -t managed-agent-control-mcp .
#   docker run -p 8000:8000 \
#     -e ANTHROPIC_API_KEY=sk-ant-... \
#     -e MCP_AUTH_MODE=bearer -e MCP_BEARER_TOKEN=$(openssl rand -hex 32) \
#     managed-agent-control-mcp

# syntax=docker/dockerfile:1

# Base image pinned by immutable digest (not just the mutable tag) so a moved or
# compromised tag can't swap the base out from under a build. Dependabot bumps the
# tag + digest together; both stages stay on the same pinned image.
# ---- build the wheel ---------------------------------------------------------
FROM python:3.14-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97 AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

# ---- runtime -----------------------------------------------------------------
FROM python:3.14-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97
RUN useradd --create-home --uid 10001 app
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
USER app

ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8000
EXPOSE 8000

# --http selects the uvicorn transport (see managed_agents_mcp/__main__.py).
ENTRYPOINT ["python", "-m", "managed_agents_mcp", "--http"]
