# Contributing

Thanks for your interest in improving **managed-agent-control-mcp**! Contributions
of all kinds are welcome — bug reports, docs, and code.

## Ground rules

- Be respectful. This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
- For anything non-trivial, open an issue first to discuss the approach before
  you invest time in a PR.
- Never report security issues in public — see [SECURITY.md](SECURITY.md).

## Development setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
git clone https://github.com/modus-agendi/managed-agent-control-mcp
cd managed-agent-control-mcp
uv sync --all-extras
uv run pre-commit install        # optional but recommended
```

Run the server locally over stdio (only `ANTHROPIC_API_KEY` is required):

```bash
ANTHROPIC_API_KEY=sk-ant-... uv run python -m managed_agents_mcp
```

Inspect it interactively with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector uv run python -m managed_agents_mcp
```

## Checks (run before opening a PR)

```bash
uv run ruff format --check
uv run ruff check
uv run pyright
uv run pytest                    # unit + transport + acceptance + security; no network
```

The opt-in tiers hit the real platform / bill tokens:

```bash
RUN_LIVE=1 ANTHROPIC_API_KEY=sk-ant-... uv run pytest -m live          # real API
RUN_SCENARIOS=1 ANTHROPIC_API_KEY=sk-ant-... uv run pytest -m scenarios # real model
```

See [`docs/testing.md`](docs/testing.md) for the full test pyramid and the
stateful fake backend.

## Pull requests

1. Fork and create a feature branch (`git checkout -b feature/your-change`).
2. Keep changes focused; every changed line should trace to the PR's stated goal.
3. Add or update tests for behavior you change.
4. Make sure all checks above pass.
5. Use clear commit messages. We loosely follow
   [Conventional Commits](https://www.conventionalcommits.org/)
   (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`) — it keeps the
   changelog tidy.
6. Open the PR against `main` and fill in the template.

## Project layout

See [`docs/architecture.md`](docs/architecture.md) for the module map (tools,
the outbound API client, the pluggable inbound-auth layer, and the transports).
