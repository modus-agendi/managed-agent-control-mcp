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
ARG PYTHON_VERSION=3.13

# ---- build the wheel ---------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

# ---- runtime -----------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim
RUN useradd --create-home --uid 10001 app
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
USER app

ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8000
EXPOSE 8000

# --http selects the uvicorn transport (see managed_agents_mcp/__main__.py).
ENTRYPOINT ["python", "-m", "managed_agents_mcp", "--http"]
