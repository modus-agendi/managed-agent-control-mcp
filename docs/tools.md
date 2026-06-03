# Tools reference

Every tool returns a compact JSON object. Large fields (e.g. full event content)
are truncated; event lists are capped and paged with a cursor.

IDs follow the platform's conventions: `agent_*`, `env_*`, `sesn_*`.

## Discovery (read-only)

### `agent_list(limit?, page?)`
List agents as lightweight summaries (`id`, `name`, `model`, `description`,
timestamps). Returns `{ agents, count, has_more, next_page }`. When `has_more` is
true, pass the returned `next_page` token back as `page`.

### `agent_get(agent_id)`
Full configuration for one agent (model, system prompt, tools, MCP servers, skills).

### `environment_list(limit?, page?)`
List sandbox environments as summaries (`id`, `name`, timestamps). Page via the
returned `next_page` token.

### `environment_get(environment_id)`
Full environment configuration (packages, networking policy).

### `vault_list(limit?, page?)`
List credential vaults as summaries (`id`, `display_name`, `metadata`, timestamps).
Find the `vlt_*` to attach via `session_start(vault_ids=…)` for agents whose
MCP servers need stored credentials. Page via the returned `next_page` token.

### `vault_get(vault_id)`
One vault's metadata by `vlt_*` id. Secret values are never returned.

### `memory_store_list(limit?, page?)`
List memory stores as summaries (`id`, `name`, `description`, timestamps). A
`memstore_*` store is a persistent, cross-session text collection the agent mounts
as a directory. Page via the returned `next_page` token.

### `memory_store_get(memory_store_id)`
One memory store's details by `memstore_*` id (name, description, timestamps).

## Start

> **Match resources to the agent first.** A managed agent only works correctly with
> *its own* environment, vault(s), and memory store(s). Before `session_start`,
> `agent_get` the agent, then pick the resources that belong to it by matching each
> resource's `name` / `description` / `metadata` (resources are commonly tagged
> `metadata.agent_name=<agent>` or named `<agent>-vault` / `<agent>-memory`). Starting
> bare or with mismatched resources causes failed tool auth, lost memory, and bad
> outcomes. The tool descriptions enforce this so MCP clients (e.g. Claude.ai) do it.

### `session_start(agent_id, environment_id, message?, vault_ids?, memory_store_ids?, agent_version?)`
Create a session (provision the sandbox) and, if `message` is given, send it as
the first `user.message`. `agent_version` pins a version (default: latest).
`vault_ids` attach stored MCP credentials (`vlt_*`); `memory_store_ids` attach
persistent memory (`memstore_*`, mounted in the sandbox). Returns
`{ session_id, status, message_sent, next_step }`.

## Observe (poll)

### `session_get(session_id)`
Current `status` (`idle` / `running` / `rescheduling` / `terminated`) and token
`usage`. `idle` with `stop_reason.type == "requires_action"` means the agent is
waiting on a tool confirmation.

### `session_list(agent_id?, statuses?, limit?, page?)`
List sessions (optionally filtered by `agent_id` and/or `statuses`) as
`{ id, status, created_at }`. Page via the returned `next_page` token.

### `session_events(session_id, types?, since?, limit?, page?)`
The agent's output and activity, oldest-first. Returns
`{ events, count, next_since, next_page, has_more }`. Poll: pass the returned
`next_since` back as `since` to fetch only events recorded after the last batch.
Filter with `types`, e.g. `["agent.message"]` for text, or
`["agent.tool_use", "agent.tool_result"]` for tool activity. Within a large batch,
page via `next_page`. `limit` defaults to 50 (max 200).

Common event types: `agent.message`, `agent.thinking`, `agent.tool_use` /
`agent.tool_result`, `agent.mcp_tool_use` / `agent.mcp_tool_result`,
`session.status_idle` (carries `stop_reason`), `session.error`.

## Interact

### `session_message(session_id, text)`
Send a `user.message` — start work, reply, or resume an idle session.

### `session_interrupt(session_id, then_message?)`
Send `user.interrupt`; if `then_message` is given it follows immediately to
redirect the agent.

### `session_respond(session_id, tool_use_id, result, deny_message?)`
Resolve a pending tool confirmation. `tool_use_id` is a blocking event id from
`stop_reason.event_ids`; `result` is `"allow"` or `"deny"` (add `deny_message`
to explain a denial).

## Destructive (gated)

Disabled when `MCP_ALLOW_DESTRUCTIVE=false`.

### `session_archive(session_id)`
Stop accepting new events but keep history.

### `session_delete(session_id)`
Permanently remove the session (history + sandbox). A `running` session must be
interrupted first.

## A typical loop

```text
agent_list()                       → pick agent_123
environment_list()                 → pick env_abc
session_start(agent_123, env_abc, message="Summarize the repo README")
   → { session_id: sesn_9, ... }
session_events(sesn_9)             → read agent.message events; note next_since
session_get(sesn_9)                → status: idle  (turn complete)
session_message(sesn_9, "Now open a PR with the summary")
session_events(sesn_9, since=<next_since>)      → poll for new output
session_delete(sesn_9)             → clean up
```
