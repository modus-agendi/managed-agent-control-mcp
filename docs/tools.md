# Tools reference

Every tool returns a compact JSON object. Large fields (e.g. full event content)
are truncated; event lists are capped and paged with a cursor.

IDs follow the platform's conventions: `agent_*`, `env_*`, `sesn_*`.

## Discovery (read-only)

### `agent_list(limit?, after_id?)`
List agents as lightweight summaries (`id`, `name`, `model`, `description`,
timestamps). Returns `{ agents, count, has_more, last_id }`. Page by passing the
returned `last_id` as `after_id`.

### `agent_get(agent_id)`
Full configuration for one agent (model, system prompt, tools, MCP servers, skills).

### `environment_list(limit?, after_id?)`
List sandbox environments as summaries (`id`, `name`, timestamps).

### `environment_get(environment_id)`
Full environment configuration (packages, networking policy).

## Start

### `session_start(agent_id, environment_id, message?, vault_ids?, agent_version?)`
Create a session (provision the sandbox) and, if `message` is given, send it as
the first `user.message`. `agent_version` pins a version (default: latest).
`vault_ids` attach stored MCP credentials. Returns
`{ session_id, status, message_sent, next_step }`.

## Observe (poll)

### `session_get(session_id)`
Current `status` (`idle` / `running` / `rescheduling` / `terminated`) and token
`usage`. `idle` with `stop_reason.type == "requires_action"` means the agent is
waiting on a tool confirmation.

### `session_list(agent_id?, limit?, after_id?)`
List sessions (optionally for one agent) as `{ id, status, created_at }`.

### `session_events(session_id, types?, after_event_id?, limit?)`
The agent's output and activity. Returns `{ events, count, last_event_id, has_more }`.
Poll: pass the returned `last_event_id` as `after_event_id` to fetch only new
events. Filter with `types`, e.g. `["agent.message"]` for text, or
`["agent.tool_use", "agent.tool_result"]` for tool activity. `limit` defaults to
50 (max 200).

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
session_events(sesn_9)             → read agent.message events; note last_event_id
session_get(sesn_9)                → status: idle  (turn complete)
session_message(sesn_9, "Now open a PR with the summary")
session_events(sesn_9, after_event_id=<last>)   → poll for new output
session_delete(sesn_9)             → clean up
```
