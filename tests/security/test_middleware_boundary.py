"""Security: the auth middleware + OAuth-route boundary on the shipped ASGI app.

Verifies public-path bypass is exact (not prefix-sloppy), that protected paths
401 with the right `WWW-Authenticate`, and that the Cognito facade + discovery
documents are shaped correctly. No lifespan is needed: these paths are handled
before (or instead of) the mounted MCP app.
"""

from __future__ import annotations

import httpx

from managed_agents_mcp.app.asgi import build_app
from managed_agents_mcp.app.auth.bearer import StaticBearerAuthenticator
from managed_agents_mcp.app.auth.cognito import CognitoAuthenticator
from managed_agents_mcp.server import mcp

HOSTED_UI = "https://demo.auth.eu-central-1.amazoncognito.com"


def _cognito_app():
    auth = CognitoAuthenticator(
        issuer="https://cognito-idp.eu-central-1.amazonaws.com/pool",
        jwks_url="https://cognito-idp.eu-central-1.amazonaws.com/pool/.well-known/jwks.json",
        hosted_ui_url=HOSTED_UI,
        audiences=["client-1"],
    )
    return build_app(mcp, auth)


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_cognito_protected_resource_metadata_advertises_self():
    async with _client(_cognito_app()) as http:
        r = await http.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"] == "http://test/mcp"
    assert body["authorization_servers"] == ["http://test"]  # facade => self is the AS


async def test_cognito_authorization_server_metadata():
    async with _client(_cognito_app()) as http:
        r = await http.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    body = r.json()
    assert body["authorization_endpoint"] == "http://test/authorize"
    assert body["token_endpoint"] == "http://test/token"


async def test_cognito_authorize_redirects_to_hosted_ui():
    async with _client(_cognito_app()) as http:
        r = await http.get("/authorize?response_type=code&client_id=x&state=abc")
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(f"{HOSTED_UI}/oauth2/authorize")
    assert "state=abc" in loc


async def test_register_stub_is_501():
    async with _client(_cognito_app()) as http:
        r = await http.post("/register", json={})
    assert r.status_code == 501


async def test_protected_path_401_with_resource_metadata():
    async with _client(_cognito_app()) as http:
        r = await http.get("/mcp")
    assert r.status_code == 401
    assert "resource_metadata=" in r.headers.get("www-authenticate", "")


async def test_public_path_match_is_exact_not_prefix():
    # "/authorize" is an EXACT public path; "/authorizeX" must NOT slip past auth.
    async with _client(_cognito_app()) as http:
        r = await http.get("/authorizeX")
    assert r.status_code == 401


async def test_bearer_has_no_discovery_and_plain_challenge():
    app = build_app(mcp, StaticBearerAuthenticator("s3cret"))
    async with _client(app) as http:
        denied = await http.get("/mcp")
        # bearer mode exposes no OAuth discovery — the well-known path isn't public.
        wellknown = await http.get("/.well-known/oauth-protected-resource")
    assert denied.status_code == 401
    assert denied.headers.get("www-authenticate") == 'Bearer realm="mcp"'
    assert wellknown.status_code == 401
