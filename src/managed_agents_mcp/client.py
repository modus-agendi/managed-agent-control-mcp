"""Async HTTP client for the Claude Managed Agents API.

A thin, faithful wrapper over the documented REST endpoints
(``https://api.anthropic.com/v1/{agents,environments,sessions}``). We speak REST
directly with ``httpx`` rather than the ``anthropic`` SDK so that:

  - the beta-API contract is pinned exactly here (headers, ``types[]`` query
    params, cursor pagination) instead of tracking an evolving SDK surface,
  - the dependency surface stays minimal, and
  - every call is trivially mockable with ``respx`` in unit tests.

The client is intentionally dumb — it returns the API's JSON verbatim. Shaping,
trimming, and guardrails live in ``server.py``. If you later prefer the official
SDK, this module is the single seam to swap.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from . import config


def _seg(value: str) -> str:
    """Percent-encode one URL path segment.

    Path ids (``agent_id``, ``session_id``, …) originate from the model / MCP
    client. Encoding them with ``safe=""`` (so ``/``, ``..``, ``?``, ``#`` are
    escaped too) prevents a crafted id from reshaping the request path or query
    against the Managed Agents API — which would otherwise run under the
    operator's key.
    """
    return quote(str(value), safe="")


# Bound how long a single API call may take. Managed Agents control-plane calls
# return promptly (we never open the SSE stream from here), so a modest timeout
# both keeps tools responsive and caps a hung upstream.
_TIMEOUT = httpx.Timeout(30.0)


class ManagedAgentsError(RuntimeError):
    """Base error for Managed Agents API problems."""


class ManagedAgentsAPIError(ManagedAgentsError):
    """A non-2xx response from the Managed Agents API.

    Carries the HTTP status and the upstream error type/message so tools can
    surface something actionable instead of a bare stack trace.
    """

    def __init__(self, status_code: int, error_type: str | None, message: str) -> None:
        self.status_code = status_code
        self.error_type = error_type
        self.message = message
        detail = f" ({error_type})" if error_type else ""
        super().__init__(f"Managed Agents API error {status_code}{detail}: {message}")


class ManagedAgentsClient:
    """Async client bound to one principal (single-tenant: principal is unused)."""

    def __init__(self, http: httpx.AsyncClient | None = None, principal: Any = None) -> None:
        self._http = http
        self._principal = principal

    @property
    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=config.settings().base_url, timeout=_TIMEOUT)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resp = await self._client.request(
            method,
            path,
            params=params,
            json=json,
            headers=config.auth_headers(self._principal),
        )
        if resp.status_code >= 400:
            raise _to_api_error(resp)
        if not resp.content:
            return {}
        return resp.json()

    # ---- agents (read-only discovery) ----------------------------------------

    async def agents_list(
        self, *, limit: int | None = None, page: str | None = None, order: str | None = None
    ) -> dict[str, Any]:
        return await self._request("GET", "/v1/agents", params=_page_params(limit, page, order))

    async def agent_get(self, agent_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/agents/{_seg(agent_id)}")

    # ---- environments (read-only discovery) ----------------------------------

    async def environments_list(
        self, *, limit: int | None = None, page: str | None = None, order: str | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "GET", "/v1/environments", params=_page_params(limit, page, order)
        )

    async def environment_get(self, environment_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/environments/{_seg(environment_id)}")

    # ---- vaults (read-only discovery) ----------------------------------------

    async def vaults_list(
        self, *, limit: int | None = None, page: str | None = None, order: str | None = None
    ) -> dict[str, Any]:
        return await self._request("GET", "/v1/vaults", params=_page_params(limit, page, order))

    async def vault_get(self, vault_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/vaults/{_seg(vault_id)}")

    # ---- memory stores (read-only discovery) ---------------------------------

    async def memory_stores_list(
        self, *, limit: int | None = None, page: str | None = None, order: str | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "GET", "/v1/memory_stores", params=_page_params(limit, page, order)
        )

    async def memory_store_get(self, memory_store_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/memory_stores/{_seg(memory_store_id)}")

    # ---- sessions ------------------------------------------------------------

    async def session_create(
        self,
        agent_id: str,
        environment_id: str,
        *,
        agent_version: int | None = None,
        vault_ids: list[str] | None = None,
        memory_store_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        # Bare string → latest agent version; object form pins a specific version.
        agent: Any = (
            {"type": "agent", "id": agent_id, "version": agent_version}
            if agent_version is not None
            else agent_id
        )
        body: dict[str, Any] = {"agent": agent, "environment_id": environment_id}
        if vault_ids:
            body["vault_ids"] = vault_ids
        if memory_store_ids:
            # Memory stores attach through the `resources` array (the API fills in
            # name/description/mount_path from the store itself).
            body["resources"] = [
                {"type": "memory_store", "memory_store_id": m} for m in memory_store_ids
            ]
        return await self._request("POST", "/v1/sessions", json=body)

    async def session_get(self, session_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/sessions/{_seg(session_id)}")

    async def sessions_list(
        self,
        agent_id: str | None = None,
        *,
        statuses: list[str] | None = None,
        limit: int | None = None,
        page: str | None = None,
        order: str | None = None,
    ) -> dict[str, Any]:
        params = _page_params(limit, page, order)
        if agent_id:
            params["agent_id"] = agent_id
        if statuses:
            params["statuses[]"] = statuses
        return await self._request("GET", "/v1/sessions", params=params)

    async def session_archive(self, session_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/v1/sessions/{_seg(session_id)}/archive")

    async def session_delete(self, session_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/v1/sessions/{_seg(session_id)}")

    # ---- events --------------------------------------------------------------

    async def events_send(self, session_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._request(
            "POST", f"/v1/sessions/{_seg(session_id)}/events", json={"events": events}
        )

    async def events_list(
        self,
        session_id: str,
        *,
        types: list[str] | None = None,
        since: str | None = None,
        limit: int | None = None,
        page: str | None = None,
        order: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = _page_params(limit, page, order)
        if types:
            # The API expects a repeated `types[]` query param (one per value).
            params["types[]"] = types
        if since:
            # Incremental polling: only events recorded after this timestamp.
            params["created_at[gt]"] = since
        return await self._request("GET", f"/v1/sessions/{_seg(session_id)}/events", params=params)


def _page_params(
    limit: int | None = None, page: str | None = None, order: str | None = None
) -> dict[str, Any]:
    """Managed Agents list pagination params, omitting any that are unset.

    Pagination is page-token based: a list response returns a `next_page` token;
    pass it back as `page` to fetch the next page. `order` is "asc" | "desc".
    """
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if page:
        params["page"] = page
    if order:
        params["order"] = order
    return params


def _to_api_error(resp: httpx.Response) -> ManagedAgentsAPIError:
    """Parse an Anthropic error body into a typed exception (best-effort)."""
    error_type: str | None = None
    message = resp.reason_phrase or "request failed"
    try:
        body = resp.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            error_type = err.get("type")
            message = err.get("message", message)
    except (ValueError, AttributeError):
        if resp.text:
            message = resp.text[:500]
    return ManagedAgentsAPIError(resp.status_code, error_type, message)
