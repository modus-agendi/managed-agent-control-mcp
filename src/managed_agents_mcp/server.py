"""MCP server: control Claude Managed Agents.

Tool tiers (see each tool's docstring — those are written as activation prompts
for the model, not human docs):

  discover   agent_list, agent_get, environment_list, environment_get,
             vault_list, vault_get, memory_store_list, memory_store_get
  start      session_start
  observe    session_get, session_list, session_events   (poll; no live stream)
  interact   session_message, session_interrupt, session_respond
  destructive (gated)  session_archive, session_delete

The model observes a running agent by *polling* `session_events` / `session_get`,
because MCP tool calls are request/response — there is no way to stream the
agent's live output back into the conversation. Tools return compact JSON; large
event payloads are truncated (poll newer events with `since`, page with `next_page`).
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from . import client, guardrails

# Server-level guidance for the model. Kept well under the 2KB that clients
# (e.g. Claude Code) truncate to, with the start→observe→interact loop first.
_INSTRUCTIONS = """\
Control Claude Managed Agents: start an agent, watch it work, and steer it.

Typical loop:
1. Discover — agent_list / environment_list to find an agent_* id and an env_* id
   (or use ones the user gives you). If the agent uses MCP tools that need stored
   credentials, also vault_list to find its vlt_* vault.
2. Start — session_start(agent_id, environment_id, message=..., vault_ids=[…]) creates
   a session and sends the first instruction; it returns a session_id. Attach
   vault_ids for any agent whose MCP servers require auth, or they fail to connect.
3. Observe (POLL — there is no live stream) — call session_get(session_id) for status
   and session_events(session_id, since=...) for new output. A turn is done when status
   is "idle". Reuse the returned next_since as the `since` argument to fetch only newer
   events on the next poll.
4. Interact — session_message to continue, session_interrupt to stop/redirect, and
   session_respond to approve/deny a tool the agent is waiting on (status "idle" with a
   requires_action stop reason).
5. End — session_archive (stop new events, keep history) or session_delete (remove).

Sessions persist across turns; resume by sending another message. Token usage is on the
session object. This server acts within one operator's Anthropic workspace.
"""

mcp: FastMCP = FastMCP("managed-agent-control", instructions=_INSTRUCTIONS)

# Bounds so a single tool call can't dump an unbounded payload into the model.
_DEFAULT_EVENT_LIMIT = 50
_MAX_EVENT_LIMIT = 200
_MAX_FIELD_CHARS = 6000

# Reused across calls (persists in stdio; warm-reused on Lambda). Single-tenant,
# so no per-principal client is needed yet.
_CLIENT = client.ManagedAgentsClient()


def _client() -> client.ManagedAgentsClient:
    return _CLIENT


# ---- discovery tier ----------------------------------------------------------


@mcp.tool()
async def agent_list(limit: int | None = None, page: str | None = None) -> dict:
    """List managed agents in the workspace (lightweight summaries).

    Call this to find an `agent_*` id to start a session with, unless the user
    already gave you one. Returns id, name, model, and description per agent. Use
    `agent_get` for full configuration. When `has_more` is true, pass the returned
    `next_page` token as `page` to fetch the next page.
    """
    data = await _client().agents_list(limit=limit, page=page)
    return _list_envelope(data, _summarize_agent, "agents")


@mcp.tool()
async def agent_get(agent_id: str) -> dict:
    """Get one agent's full configuration by `agent_*` id.

    Use after `agent_list` to inspect an agent's model, system prompt, tools,
    MCP servers, and skills before starting a session.
    """
    return _truncate(await _client().agent_get(agent_id))


@mcp.tool()
async def environment_list(limit: int | None = None, page: str | None = None) -> dict:
    """List sandbox environments (lightweight summaries).

    Starting a session needs an `env_*` id alongside an agent id. Call this to
    find one. Returns id, name, and timestamps per environment. Page with the
    returned `next_page` token when `has_more` is true.
    """
    data = await _client().environments_list(limit=limit, page=page)
    return _list_envelope(data, _summarize_environment, "environments")


@mcp.tool()
async def environment_get(environment_id: str) -> dict:
    """Get one environment's full configuration by `env_*` id (packages, networking)."""
    return _truncate(await _client().environment_get(environment_id))


@mcp.tool()
async def vault_list(limit: int | None = None, page: str | None = None) -> dict:
    """List credential vaults (lightweight summaries).

    An agent whose tools/MCP servers need stored credentials must have a `vlt_*`
    vault attached when you start its session (`session_start(..., vault_ids=[…])`),
    or those MCP servers fail to authenticate. Call this to find the right vault —
    the `display_name`/`metadata` usually identify which agent it belongs to.
    """
    data = await _client().vaults_list(limit=limit, page=page)
    return _list_envelope(data, _summarize_vault, "vaults")


@mcp.tool()
async def vault_get(vault_id: str) -> dict:
    """Get one vault's details by `vlt_*` id (display name, metadata, timestamps).

    Secret values are never returned — Anthropic stores and injects them. This is
    metadata only, to confirm the vault is the one you want before attaching it.
    """
    return _truncate(await _client().vault_get(vault_id))


@mcp.tool()
async def memory_store_list(limit: int | None = None, page: str | None = None) -> dict:
    """List memory stores (lightweight summaries: id, name, description).

    Memory stores are `memstore_*` collections of text the agent mounts as a
    directory for persistent, cross-session memory. Use this to find one (the
    `name`/`description` identify its purpose). Page via the returned `next_page`.
    """
    data = await _client().memory_stores_list(limit=limit, page=page)
    return _list_envelope(data, _summarize_memory_store, "memory_stores")


@mcp.tool()
async def memory_store_get(memory_store_id: str) -> dict:
    """Get one memory store's details by `memstore_*` id (name, description, timestamps)."""
    return _truncate(await _client().memory_store_get(memory_store_id))


# ---- start tier --------------------------------------------------------------


@mcp.tool()
async def session_start(
    agent_id: str,
    environment_id: str,
    message: str | None = None,
    vault_ids: list[str] | None = None,
    agent_version: int | None = None,
) -> dict:
    """Start a managed-agent session: provision a sandbox and (optionally) kick off work.

    This is the main entry point. Pass `message` to send the agent its first
    instruction immediately; omit it to only provision the session and send work
    later with `session_message`. Pin `agent_version` to run a specific version
    (default: latest). `vault_ids` attach stored MCP credentials.

    Returns the `session_id`. After starting, OBSERVE by polling
    `session_get`/`session_events` until status is "idle".
    """
    guardrails.check_agent_allowed(agent_id)
    guardrails.check_environment_allowed(environment_id)

    session = await _client().session_create(
        agent_id, environment_id, agent_version=agent_version, vault_ids=vault_ids
    )
    session_id = session.get("id", "")

    message_sent = False
    if message:
        await _client().events_send(session_id, [_user_message(message)])
        message_sent = True

    guardrails.audit(
        "session_start",
        agent_id=agent_id,
        environment_id=environment_id,
        session_id=session_id,
        message_sent=message_sent,
    )
    return {
        "session_id": session_id,
        "status": session.get("status"),
        "message_sent": message_sent,
        "next_step": (
            "Poll session_events(session_id, since=...) and session_get(session_id) "
            "until status is 'idle'."
        ),
    }


# ---- observe tier (poll) -----------------------------------------------------


@mcp.tool()
async def session_get(session_id: str) -> dict:
    """Get a session's current status and token usage.

    Status is one of: idle (waiting for input — done with its turn), running
    (working), rescheduling (retrying), terminated (ended on error). When idle
    with a `stop_reason` of `requires_action`, the agent is waiting on a tool
    confirmation — use `session_respond`.
    """
    return _truncate(await _client().session_get(session_id))


@mcp.tool()
async def session_list(
    agent_id: str | None = None,
    statuses: list[str] | None = None,
    limit: int | None = None,
    page: str | None = None,
) -> dict:
    """List sessions, optionally filtered to one `agent_id` and/or `statuses`.

    `statuses` filters by session status (e.g. ["running", "idle"]). Returns id +
    status each; page with the returned `next_page` token when `has_more` is true.
    """
    data = await _client().sessions_list(
        agent_id=agent_id, statuses=statuses, limit=limit, page=page
    )
    return _list_envelope(data, _summarize_session, "sessions")


@mcp.tool()
async def session_events(
    session_id: str,
    types: list[str] | None = None,
    since: str | None = None,
    limit: int | None = None,
    page: str | None = None,
) -> dict:
    """Read a session's events — the agent's output and activity. POLL this to observe.

    To observe new output as the agent works, poll: pass the returned `next_since`
    back as `since` on the next call to fetch only events recorded after the last
    batch (events are returned oldest-first). Filter with `types` (e.g.
    ["agent.message"] for just the agent's text, or ["agent.tool_use",
    "agent.tool_result"] for tool activity). When `has_more` is true within a
    batch, pass the returned `next_page` token as `page`. Large payloads truncated.

    Common types: agent.message (text), agent.thinking, agent.tool_use /
    agent.tool_result, agent.mcp_tool_use, session.status_idle (with stop_reason).
    """
    capped = min(limit or _DEFAULT_EVENT_LIMIT, _MAX_EVENT_LIMIT)
    data = await _client().events_list(
        session_id, types=types, since=since, limit=capped, page=page, order="asc"
    )
    events = data.get("data", []) if isinstance(data, dict) else []
    # next_since drives the next poll: the latest processed_at we've seen (events
    # still queued have processed_at=null and are skipped here).
    timestamps = [str(ts) for e in events if isinstance(e, dict) and (ts := e.get("processed_at"))]
    next_since = max(timestamps) if timestamps else since
    return {
        "session_id": session_id,
        "count": len(events),
        "events": _truncate(events),
        "next_since": next_since,
        "next_page": data.get("next_page") if isinstance(data, dict) else None,
        "has_more": bool(data.get("next_page")) if isinstance(data, dict) else False,
    }


# ---- interact tier -----------------------------------------------------------


@mcp.tool()
async def session_message(session_id: str, text: str) -> dict:
    """Send a user message to the agent — start work, reply, or continue a turn.

    Use to give the agent a new instruction or to resume an idle session. After
    sending, OBSERVE by polling `session_events`.
    """
    await _client().events_send(session_id, [_user_message(text)])
    guardrails.audit("session_message", session_id=session_id)
    return {
        "ok": True,
        "session_id": session_id,
        "next_step": "Poll session_events / session_get until status is 'idle'.",
    }


@mcp.tool()
async def session_interrupt(session_id: str, then_message: str | None = None) -> dict:
    """Interrupt a running agent, optionally redirecting it with a new instruction.

    Sends a user.interrupt; if `then_message` is given, it follows immediately so
    the agent stops what it's doing and takes the new direction.
    """
    events: list[dict[str, Any]] = [{"type": "user.interrupt"}]
    if then_message:
        events.append(_user_message(then_message))
    await _client().events_send(session_id, events)
    guardrails.audit("session_interrupt", session_id=session_id, redirected=bool(then_message))
    return {"ok": True, "session_id": session_id, "redirected": bool(then_message)}


@mcp.tool()
async def session_respond(
    session_id: str, tool_use_id: str, result: str, deny_message: str | None = None
) -> dict:
    """Approve or deny a tool call the agent is waiting on (a permission policy gate).

    When `session_get` shows status "idle" with stop_reason `requires_action`, the
    agent paused for confirmation. The blocking event ids are in
    `stop_reason.event_ids`. Call this with `tool_use_id` = the blocking event id
    and `result` = "allow" or "deny" (add `deny_message` to explain a denial).
    """
    if result not in {"allow", "deny"}:
        raise ValueError('result must be "allow" or "deny"')
    event: dict[str, Any] = {
        "type": "user.tool_confirmation",
        "tool_use_id": tool_use_id,
        "result": result,
    }
    if deny_message and result == "deny":
        event["deny_message"] = deny_message
    await _client().events_send(session_id, [event])
    guardrails.audit("session_respond", session_id=session_id, result=result)
    return {"ok": True, "session_id": session_id, "result": result}


# ---- destructive tier (gated) ------------------------------------------------


@mcp.tool()
async def session_archive(session_id: str) -> dict:
    """Archive a session: stop accepting new events but keep its history. Reversible-ish."""
    guardrails.check_destructive_allowed("session_archive")
    await _client().session_archive(session_id)
    guardrails.audit("session_archive", session_id=session_id)
    return {"ok": True, "session_id": session_id, "archived": True}


@mcp.tool()
async def session_delete(session_id: str) -> dict:
    """Permanently delete a session (history + sandbox). Cannot delete a running session."""
    guardrails.check_destructive_allowed("session_delete")
    await _client().session_delete(session_id)
    guardrails.audit("session_delete", session_id=session_id)
    return {"ok": True, "session_id": session_id, "deleted": True}


# ---- helpers -----------------------------------------------------------------


def _user_message(text: str) -> dict[str, Any]:
    return {"type": "user.message", "content": [{"type": "text", "text": text}]}


def _list_envelope(data: Any, summarize: Any, key: str) -> dict:
    """Shape an API list response into {<key>: [summary,...], has_more, next_page}."""
    items = data.get("data", []) if isinstance(data, dict) else []
    next_page = data.get("next_page") if isinstance(data, dict) else None
    return {
        key: [summarize(i) for i in items if isinstance(i, dict)],
        "count": len(items),
        "has_more": bool(next_page),
        "next_page": next_page,
    }


def _summarize_agent(a: dict) -> dict:
    # `model` may be a bare string or an object like {"model": "...", "speed": "..."}.
    model = a.get("model")
    if isinstance(model, dict):
        model = model.get("model")
    return {
        "id": a.get("id"),
        "name": a.get("name"),
        "model": model,
        "description": a.get("description"),
        "created_at": a.get("created_at"),
        "archived_at": a.get("archived_at"),
    }


def _summarize_environment(e: dict) -> dict:
    return {
        "id": e.get("id"),
        "name": e.get("name"),
        "created_at": e.get("created_at"),
        "archived_at": e.get("archived_at"),
    }


def _summarize_vault(v: dict) -> dict:
    return {
        "id": v.get("id"),
        "display_name": v.get("display_name"),
        "metadata": v.get("metadata"),
        "created_at": v.get("created_at"),
        "archived_at": v.get("archived_at"),
    }


def _summarize_memory_store(m: dict) -> dict:
    return {
        "id": m.get("id"),
        "name": m.get("name"),
        "description": m.get("description"),
        "created_at": m.get("created_at"),
        "archived_at": m.get("archived_at"),
    }


def _summarize_session(s: dict) -> dict:
    return {
        "id": s.get("id"),
        "status": s.get("status"),
        "created_at": s.get("created_at"),
    }


def _truncate(value: Any, max_chars: int = _MAX_FIELD_CHARS) -> Any:
    """Recursively truncate long strings so a tool result stays a sane size."""
    if isinstance(value, str):
        if len(value) > max_chars:
            return value[:max_chars] + f"…[truncated {len(value) - max_chars} chars]"
        return value
    if isinstance(value, dict):
        return {k: _truncate(v, max_chars) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(v, max_chars) for v in value]
    return value
