# Examples

End-to-end, **vendor-specific** walkthroughs for deploying and connecting
`managed-agent-control-mcp`. The server itself stays generic — everything
specific to a particular host or identity provider lives here, isolated from the
core repo.

| Example | Host | Auth | What it shows |
|---|---|---|---|
| [`fly-io-workos-oauth/`](fly-io-workos-oauth/) | Fly.io | WorkOS AuthKit (OAuth) | Deploy the server, secure it with OAuth (no infra, no core code), connect it to Claude.ai, and drive a managed coding agent from a chat. |

> These use specific vendors as concrete examples. None of it is required by the
> server — the same image runs anywhere, and any OIDC provider works in `oidc`
> mode. See the top-level [`docs/`](../docs/) for the generic reference.
