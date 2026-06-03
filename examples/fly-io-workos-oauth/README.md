# Deploy on Fly.io with WorkOS AuthKit (OAuth) → control a coding agent from Claude.ai

A minimal, end-to-end walkthrough: deploy `managed-agent-control-mcp` to **Fly.io**,
secure it with **OAuth via WorkOS AuthKit**, add it to **Claude.ai** as a custom
connector, and then **start and observe a Managed coding agent** (our Fibonacci
example) straight from a chat.

> [!NOTE]
> This folder is the only **vendor-specific** part. The server is generic: the
> same container runs anywhere, and WorkOS is just OAuth *configuration* (env
> vars) — there are **no Fly/WorkOS code or dependencies in the core repo**.

## How it fits together

```
You ──login/consent──▶ WorkOS AuthKit  (Authorization Server: login, consent, tokens, DCR)
                              │ issues JWT (aud = your MCP URL)
                              ▼
Claude.ai ──Bearer JWT──▶ managed-agent-control-mcp on Fly.io ──x-api-key──▶ Managed Agents API
 (MCP client)             (Resource Server: validates JWT in `oidc` mode)     (your agent runs here)
```

Your server only **validates** WorkOS-issued JWTs (our built-in `oidc` mode).
AuthKit hosts the entire login/consent/token flow — so there's nothing to build.

## Prerequisites

- An **Anthropic API key** with Managed Agents access (`sk-ant-…`).
- A **managed agent + environment** to control. Don't have one? See
  [Appendix A](#appendix-a--create-a-sample-coding-agent) to create the Fibonacci
  coding agent in ~1 minute.
- **flyctl** installed (`brew install flyctl`) and a Fly.io account (`fly auth login`).
- A free **WorkOS** account.
- This repo cloned locally (you deploy from its root).

## Step 0 — Pick your app name

Fly app names are globally unique and become your URL. We'll use `fib-mcp`
→ `https://fib-mcp.fly.dev`. Substitute your own everywhere below. You need this
URL in the next step, so decide it now.

## Step 1 — Set up WorkOS AuthKit

1. Sign up at [workos.com](https://workos.com) and open the **Dashboard**.
2. **Authentication → AuthKit**: note your **AuthKit domain**, e.g.
   `https://your-project-12345.authkit.app`. This is your OAuth issuer.
3. **Connect → Configuration**:
   - Enable **Dynamic Client Registration (DCR)** (and **Client ID Metadata
     Document** if offered) — this lets Claude.ai register itself, so you leave
     the connector's Client ID/Secret blank.
   - Add a **Resource Indicator** equal to your MCP endpoint URL:
     `https://fib-mcp.fly.dev/mcp`. WorkOS will stamp issued tokens with
     `aud = https://fib-mcp.fly.dev/mcp`, which your server checks.
4. (Recommended) Restrict who can sign in (AuthKit → invite-only, or limit to your
   email/domain) so only you can mint tokens for your server.

You now have two values: the **issuer** (`…​.authkit.app`) and its **JWKS**
(`…​.authkit.app/oauth2/jwks`).

## Step 2 — Create the Fly app (don't deploy yet)

```bash
fly auth login
fly apps create fib-mcp        # reserves the name + URL
```

## Step 3 — Set the server's config as Fly secrets

```bash
fly secrets set --app fib-mcp \
  ANTHROPIC_API_KEY="sk-ant-..." \
  MCP_AUTH_MODE="oidc" \
  MCP_OIDC_ISSUER="https://your-project-12345.authkit.app" \
  MCP_OIDC_JWKS_URL="https://your-project-12345.authkit.app/oauth2/jwks" \
  MCP_OIDC_AUDIENCE="https://fib-mcp.fly.dev/mcp" \
  MCP_PUBLIC_URL="https://fib-mcp.fly.dev" \
  MCP_ALLOWED_AGENT_IDS="agent_01..."     # optional: lock to your agent
```

(See [`.env.example`](.env.example) for the same set.)

## Step 4 — Deploy and verify

Edit [`fly.toml`](fly.toml) (set your `app` name + `primary_region`), then **from the
repo root**:

```bash
fly deploy --config examples/fly-io-workos-oauth/fly.toml
```

Verify the OAuth discovery document is correct:

```bash
curl -s https://fib-mcp.fly.dev/.well-known/oauth-protected-resource | jq
# {
#   "resource": "https://fib-mcp.fly.dev/mcp",
#   "authorization_servers": ["https://your-project-12345.authkit.app"],
#   ...
# }
```

`resource` must be your `/mcp` URL and `authorization_servers` must be your
AuthKit domain. If not, recheck `MCP_PUBLIC_URL` / `MCP_OIDC_ISSUER`.

## Step 5 — Add the connector in Claude.ai

1. Claude.ai → **Settings → Connectors → Add custom connector**.
2. **Name**: `Fibonacci Agent` (anything).
3. **Remote MCP server URL**: `https://fib-mcp.fly.dev/mcp`.
4. Leave **OAuth Client ID/Secret blank** (DCR handles registration). Click **Add**.
5. Claude.ai opens the WorkOS login → sign in & consent → the connector turns
   green. Done.

## Step 6 — Drive the Fibonacci agent from a chat

In a new Claude.ai conversation with the connector enabled, try:

> List my managed agents and environments.

then:

> Start the coding agent in that environment and have it write a Python script
> that prints the first 15 Fibonacci numbers, run it, and tell me the exact output.
> Poll until it's done, then clean up the session.

Claude will call `agent_list` / `environment_list` → `session_start` → poll
`session_events` / `session_get` → report `[0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55,
89, 144, 233, 377]` → `session_delete`. That's a Managed Agent doing real work in
a sandbox, driven entirely through the connector.

## Troubleshooting

- **`curl` of the well-known doc shows the wrong host** → `MCP_PUBLIC_URL` isn't
  your Fly URL. Fix and redeploy.
- **OAuth completes but tools 401 with an audience error** → the WorkOS
  **Resource Indicator** must exactly equal `MCP_OIDC_AUDIENCE` (your `/mcp` URL).
- **Claude.ai can't find the authorization server** → most clients follow the
  protected-resource doc to your AuthKit issuer. A few fetch
  `/.well-known/oauth-authorization-server` from the MCP server directly (our
  `oidc` mode returns 404 there). If you hit this, it needs a small generic proxy
  route in the server — open an issue; it's not normally required.
- **Live logs**: `fly logs --app fib-mcp` (auth failures print an `auth:` line).

## Cost & cleanup

- Fly `min_machines_running = 0` scales the app to zero when idle (cheap); the
  first request cold-starts it.
- Tear down: `fly apps destroy fib-mcp`. Delete the WorkOS project from its
  dashboard. The Anthropic agent/environment are separate resources — delete via
  the API/console if you created them only for this.

---

## Appendix A — Create a sample coding agent

If you don't already have an agent, create the Fibonacci coding agent (a cloud
sandbox + an agent with the bundled `bash`/edit toolset, auto-approved):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
H=(-H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" \
   -H "anthropic-beta: managed-agents-2026-04-01" -H "content-type: application/json")

# 1. A cloud sandbox environment
ENV_ID=$(curl -fsSL https://api.anthropic.com/v1/environments "${H[@]}" -d '{
  "name": "fib-sandbox",
  "config": {"type": "cloud", "networking": {"type": "unrestricted"}}
}' | jq -r .id)

# 2. A coding agent that can write + run code
AGENT_ID=$(curl -fsSL https://api.anthropic.com/v1/agents "${H[@]}" -d '{
  "name": "fib-coding-agent",
  "model": "claude-sonnet-4-6",
  "system": "You are a coding agent in a Linux sandbox. Use bash and the file tools to write and run code, then report the actual output.",
  "tools": [{"type": "agent_toolset_20260401",
             "default_config": {"permission_policy": {"type": "always_allow"}}}]
}' | jq -r .id)

echo "AGENT_ID=$AGENT_ID  ENV_ID=$ENV_ID"
```

Use those ids for `MCP_ALLOWED_AGENT_IDS` and when prompting Claude. (Prefer
Terraform for real agents — see the
[Terraform provider](https://github.com/modus-agendi/terraform-provider-anthropic-claude-managed-agents).)

## Appendix B — Security notes

- Scope the Anthropic key to the minimum needed; it's the most sensitive secret.
- Keep AuthKit sign-in restricted to you (single-owner deployment).
- Set `MCP_ALLOWED_AGENT_IDS` so a prompt-injected chat can't start arbitrary,
  token-burning agents. `MCP_ALLOW_DESTRUCTIVE=false` disables archive/delete.
