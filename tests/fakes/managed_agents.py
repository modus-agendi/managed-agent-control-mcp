"""A stateful in-memory fake of the Claude Managed Agents API.

Mounted as an ASGI app and pointed at by the server's HTTP client (via
ASGITransport), this lets acceptance + scenario tests drive the *whole*
start → observe → interact → respond → end loop deterministically — no real API,
no tokens, no per-call mocking. It models the session state machine, event
history, pagination, and the `types[]` filter.

Agent behavior is scripted by keywords in the user message text, so a test can
provoke specific server-observable outcomes:

    (default)     → one agent.message echo, then status idle (end_turn)
    "[approve]"   → an agent.tool_use, then status idle (requires_action) — awaits
                    a user.tool_confirmation before continuing
    "[big]"       → an agent.message whose text exceeds the server truncation cap
    "[multi:N]"   → N agent.message events (for pagination tests)
    "[running]"   → stays in status running (never goes idle) — e.g. to test
                    deleting a running session (409)

The fake requires the `x-api-key` header (401 otherwise), mirroring the real API.
"""

from __future__ import annotations

import re
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

_TS = "2026-01-01T00:00:00Z"
_BIG = "X" * 7000  # exceeds server _MAX_FIELD_CHARS (6000)


class FakeState:
    """Inspectable in-memory state for assertions in tests."""

    def __init__(self) -> None:
        self.agents: dict[str, dict] = {}
        self.environments: dict[str, dict] = {}
        self.vaults: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self._seq = 0

    def next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}_{self._seq:04d}"

    def seed_defaults(self) -> None:
        self.agents["agent_demo"] = {
            "id": "agent_demo",
            "name": "Demo Agent",
            "model": "claude-opus-4-7",
            "system": "You are a demo agent. " * 50,  # big-ish to prove get != list
            "description": "An agent for tests.",
            "created_at": _TS,
            "archived_at": None,
        }
        self.environments["env_demo"] = {
            "id": "env_demo",
            "name": "demo-sandbox",
            "config": {"type": "cloud", "networking": {"type": "unrestricted"}},
            "created_at": _TS,
            "archived_at": None,
        }
        self.vaults["vlt_demo"] = {
            "id": "vlt_demo",
            "type": "vault",
            "display_name": "demo-vault",
            "metadata": {"agent_name": "demo"},
            "created_at": _TS,
            "updated_at": _TS,
            "archived_at": None,
        }


def _err(status: int, type_: str, message: str) -> JSONResponse:
    return JSONResponse({"type": "error", "error": {"type": type_, "message": message}}, status)


def _list_page(items: list[dict], request: Request) -> dict:
    """Page-token pagination, mirroring the real API: a response carries `next_page`
    (here just the next offset as a string); the caller passes it back as `page`."""
    limit = int(request.query_params.get("limit", "100"))
    if request.query_params.get("order") == "desc":
        items = list(reversed(items))
    page = request.query_params.get("page")
    start = int(page) if page and page.isdigit() else 0
    window = items[start : start + limit]
    out: dict = {"data": window, "next_page": None}
    if start + limit < len(items):
        out["next_page"] = str(start + limit)
    return out


def build_fake(seed: bool = True) -> tuple[Starlette, FakeState]:
    state = FakeState()
    if seed:
        state.seed_defaults()

    def _emit(session: dict, type_: str, **fields: Any) -> dict:
        eid = state.next_id("evt")
        # Monotonically increasing, lexicographically-sortable timestamp so the
        # `created_at[gt]` (since) filter behaves like the real API.
        ts = f"2026-01-01T00:{state._seq // 60:02d}:{state._seq % 60:02d}Z"
        event = {"id": eid, "type": type_, "processed_at": ts, **fields}
        session["events"].append(event)
        return event

    def _advance(session: dict, text: str) -> list[dict]:
        """Run the scripted agent turn for a user message; return emitted events."""
        before = len(session["events"])
        if "[running]" in text:
            session["status"] = "running"
            return session["events"][before:]
        if "[approve]" in text:
            tool = _emit(session, "agent.tool_use", name="bash", input={"command": "ls"})
            session["status"] = "idle"
            session["stop_reason"] = {"type": "requires_action", "event_ids": [tool["id"]]}
            session.setdefault("pending", []).append(tool["id"])
            return session["events"][before:]
        if "[big]" in text:
            _emit(session, "agent.message", content=[{"type": "text", "text": _BIG}])
        elif m := re.search(r"\[multi:(\d+)\]", text):
            for i in range(int(m.group(1))):
                _emit(session, "agent.message", content=[{"type": "text", "text": f"part {i}"}])
        else:
            _emit(session, "agent.message", content=[{"type": "text", "text": f"echo: {text}"}])
        session["status"] = "idle"
        session["stop_reason"] = {"type": "end_turn"}
        _emit(session, "session.status_idle", stop_reason=session["stop_reason"])
        session["usage"]["output_tokens"] += 10
        return session["events"][before:]

    def _require_key(request: Request) -> JSONResponse | None:
        if not request.headers.get("x-api-key"):
            return _err(401, "authentication_error", "missing x-api-key")
        return None

    # ---- agents / environments ----------------------------------------------

    async def agents_list(request: Request):
        if e := _require_key(request):
            return e
        return JSONResponse(_list_page(list(state.agents.values()), request))

    async def agent_get(request: Request):
        if e := _require_key(request):
            return e
        aid = request.path_params["aid"]
        if aid == "agent_rate_limited":
            return _err(429, "rate_limit_error", "slow down")
        agent = state.agents.get(aid)
        return JSONResponse(agent) if agent else _err(404, "not_found_error", f"no agent {aid}")

    async def environments_list(request: Request):
        if e := _require_key(request):
            return e
        return JSONResponse(_list_page(list(state.environments.values()), request))

    async def environment_get(request: Request):
        if e := _require_key(request):
            return e
        eid = request.path_params["eid"]
        env = state.environments.get(eid)
        return JSONResponse(env) if env else _err(404, "not_found_error", f"no environment {eid}")

    async def vaults_list(request: Request):
        if e := _require_key(request):
            return e
        return JSONResponse(_list_page(list(state.vaults.values()), request))

    async def vault_get(request: Request):
        if e := _require_key(request):
            return e
        vid = request.path_params["vid"]
        vault = state.vaults.get(vid)
        return JSONResponse(vault) if vault else _err(404, "not_found_error", f"no vault {vid}")

    # ---- sessions ------------------------------------------------------------

    async def session_create(request: Request):
        if e := _require_key(request):
            return e
        body = await request.json()
        sid = state.next_id("sesn")
        state.sessions[sid] = {
            "id": sid,
            "status": "idle",
            "agent": body.get("agent"),
            "environment_id": body.get("environment_id"),
            "vault_ids": body.get("vault_ids", []),
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "events": [],
            "stop_reason": None,
            "created_at": _TS,
        }
        return JSONResponse(_public_session(state.sessions[sid]))

    async def session_get(request: Request):
        if e := _require_key(request):
            return e
        s = state.sessions.get(request.path_params["sid"])
        return JSONResponse(_public_session(s)) if s else _err(404, "not_found_error", "no session")

    async def sessions_list(request: Request):
        if e := _require_key(request):
            return e
        items = list(state.sessions.values())
        if agent_id := request.query_params.get("agent_id"):
            items = [s for s in items if _agent_id_of(s) == agent_id]
        page = _list_page([_public_session(s) for s in items], request)
        return JSONResponse(page)

    async def session_archive(request: Request):
        if e := _require_key(request):
            return e
        s = state.sessions.get(request.path_params["sid"])
        if not s:
            return _err(404, "not_found_error", "no session")
        s["archived_at"] = _TS
        return JSONResponse(_public_session(s))

    async def session_delete(request: Request):
        if e := _require_key(request):
            return e
        s = state.sessions.get(request.path_params["sid"])
        if not s:
            return _err(404, "not_found_error", "no session")
        if s["status"] == "running":
            return _err(409, "invalid_request_error", "cannot delete a running session")
        del state.sessions[request.path_params["sid"]]
        return Response(status_code=204)

    async def events_send(request: Request):
        if e := _require_key(request):
            return e
        s = state.sessions.get(request.path_params["sid"])
        if not s:
            return _err(404, "not_found_error", "no session")
        body = await request.json()
        produced: list[dict] = []
        for ev in body.get("events", []):
            produced += _handle_user_event(s, ev, _emit, _advance)
        return JSONResponse({"data": produced})

    async def events_list(request: Request):
        if e := _require_key(request):
            return e
        s = state.sessions.get(request.path_params["sid"])
        if not s:
            return _err(404, "not_found_error", "no session")
        events = s["events"]
        types = request.query_params.getlist("types[]")
        if types:
            events = [ev for ev in events if ev["type"] in types]
        since = request.query_params.get("created_at[gt]")
        if since:
            events = [ev for ev in events if (ev.get("processed_at") or "") > since]
        return JSONResponse(_list_page(events, request))

    app = Starlette(
        routes=[
            Route("/v1/agents", agents_list, methods=["GET"]),
            Route("/v1/agents/{aid}", agent_get, methods=["GET"]),
            Route("/v1/environments", environments_list, methods=["GET"]),
            Route("/v1/environments/{eid}", environment_get, methods=["GET"]),
            Route("/v1/vaults", vaults_list, methods=["GET"]),
            Route("/v1/vaults/{vid}", vault_get, methods=["GET"]),
            Route("/v1/sessions", session_create, methods=["POST"]),
            Route("/v1/sessions", sessions_list, methods=["GET"]),
            Route("/v1/sessions/{sid}", session_get, methods=["GET"]),
            Route("/v1/sessions/{sid}", session_delete, methods=["DELETE"]),
            Route("/v1/sessions/{sid}/archive", session_archive, methods=["POST"]),
            Route("/v1/sessions/{sid}/events", events_send, methods=["POST"]),
            Route("/v1/sessions/{sid}/events", events_list, methods=["GET"]),
        ]
    )
    return app, state


def _agent_id_of(session: dict) -> str | None:
    agent = session.get("agent")
    return agent.get("id") if isinstance(agent, dict) else agent


def _public_session(s: dict) -> dict:
    return {
        "id": s["id"],
        "status": s["status"],
        "usage": s["usage"],
        "stop_reason": s.get("stop_reason"),
        "agent": s.get("agent"),
        "environment_id": s.get("environment_id"),
        "created_at": s["created_at"],
        "archived_at": s.get("archived_at"),
    }


def _handle_user_event(session: dict, ev: dict, emit, advance) -> list[dict]:
    kind = ev.get("type")
    if kind == "user.message":
        text = " ".join(b.get("text", "") for b in ev.get("content", []) if b.get("type") == "text")
        return advance(session, text)
    if kind == "user.interrupt":
        session["status"] = "idle"
        session["stop_reason"] = {"type": "interrupt"}
        return [emit(session, "session.status_idle", stop_reason=session["stop_reason"])]
    if kind == "user.tool_confirmation":
        pending = session.get("pending", [])
        if ev.get("tool_use_id") in pending:
            pending.remove(ev["tool_use_id"])
            emit(
                session, "agent.tool_result", tool_use_id=ev["tool_use_id"], result=ev.get("result")
            )
            emit(session, "agent.message", content=[{"type": "text", "text": "done"}])
            session["status"] = "idle"
            session["stop_reason"] = {"type": "end_turn"}
            return [emit(session, "session.status_idle", stop_reason=session["stop_reason"])]
    return []
