from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from managed_agents_mcp.app.auth.base import AuthError, CompositeAuthenticator
from managed_agents_mcp.app.auth.bearer import StaticBearerAuthenticator
from managed_agents_mcp.app.auth.cognito import CognitoAuthenticator
from managed_agents_mcp.app.auth.oidc import OIDCAuthenticator

ISSUER = "https://issuer.example.com"


def _bearer(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


# ---- static bearer -----------------------------------------------------------


def test_bearer_accepts_exact_token():
    auth = StaticBearerAuthenticator("s3cret")
    assert auth.validate(_bearer("s3cret"), {}).subject == "static-bearer"


def test_bearer_rejects_wrong_and_missing():
    auth = StaticBearerAuthenticator("s3cret")
    with pytest.raises(AuthError):
        auth.validate(_bearer("nope"), {})
    with pytest.raises(AuthError):
        auth.validate({}, {})


# ---- composite fall-through --------------------------------------------------


def test_composite_falls_through_to_bearer_for_opaque_token():
    oidc = OIDCAuthenticator(issuer=ISSUER, jwks_url="https://issuer.example.com/jwks")
    composite = CompositeAuthenticator([oidc, StaticBearerAuthenticator("opaque")])
    # An opaque (non-JWT) token: OIDC declines, static bearer accepts.
    assert composite.validate(_bearer("opaque"), {}).subject == "static-bearer"


# ---- OIDC JWT verification ---------------------------------------------------


@pytest.fixture
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _sign(private_key, **claims) -> str:
    payload = {"iss": ISSUER, "exp": int(time.time()) + 3600, "sub": "user-1", **claims}
    return jwt.encode(payload, private_key, algorithm="RS256")


def _wire_jwks(auth: OIDCAuthenticator, public_key) -> None:
    # Bypass the network JWKS fetch with the known public key.
    auth._jwk_client = SimpleNamespace(  # type: ignore[attr-defined]
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public_key)
    )


def test_oidc_accepts_valid_token(rsa_key):
    auth = OIDCAuthenticator(issuer=ISSUER, jwks_url="x", audiences=["client-1"])
    _wire_jwks(auth, rsa_key.public_key())
    token = _sign(rsa_key, client_id="client-1", email="u@example.com")
    principal = auth.validate(_bearer(token), {})
    assert principal.subject == "user-1"
    assert principal.email == "u@example.com"


def test_oidc_rejects_non_jwt():
    auth = OIDCAuthenticator(issuer=ISSUER, jwks_url="x")
    with pytest.raises(AuthError):
        auth.validate(_bearer("opaque-token"), {})


def test_oidc_rejects_bad_audience(rsa_key):
    auth = OIDCAuthenticator(issuer=ISSUER, jwks_url="x", audiences=["expected"])
    _wire_jwks(auth, rsa_key.public_key())
    token = _sign(rsa_key, client_id="someone-else")
    with pytest.raises(AuthError):
        auth.validate(_bearer(token), {})


def test_cognito_rejects_id_token(rsa_key):
    # Cognito preset requires token_use == "access"; an ID token must be rejected.
    auth = CognitoAuthenticator(
        issuer=ISSUER, jwks_url="x", hosted_ui_url="https://ui.example.com", audiences=["c"]
    )
    _wire_jwks(auth, rsa_key.public_key())
    token = _sign(rsa_key, client_id="c", token_use="id")
    with pytest.raises(AuthError):
        auth.validate(_bearer(token), {})


def test_cognito_advertises_facade_paths():
    auth = CognitoAuthenticator(issuer=ISSUER, jwks_url="x", hosted_ui_url="https://ui.example.com")
    assert "/authorize" in auth.public_paths()
    assert auth.advertises_oauth() is True


# ---- factory: audience is required for JWT modes (H2) ------------------------


def test_factory_oidc_requires_audience(monkeypatch: pytest.MonkeyPatch):
    from managed_agents_mcp.app.auth.factory import AuthConfigError, build_authenticator

    monkeypatch.setenv("MCP_AUTH_MODE", "oidc")
    monkeypatch.setenv("MCP_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("MCP_OIDC_JWKS_URL", "https://issuer.example.com/jwks")
    # No MCP_OIDC_AUDIENCE → must refuse (skipping the check accepts any issuer token).
    with pytest.raises(AuthConfigError):
        build_authenticator()


def test_factory_oidc_audience_requirement_is_opt_out(monkeypatch: pytest.MonkeyPatch):
    from managed_agents_mcp.app.auth.factory import build_authenticator

    monkeypatch.setenv("MCP_AUTH_MODE", "oidc")
    monkeypatch.setenv("MCP_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("MCP_OIDC_JWKS_URL", "https://issuer.example.com/jwks")
    monkeypatch.setenv("MCP_OIDC_REQUIRE_AUDIENCE", "false")
    assert build_authenticator() is not None


# ---- factory: issuer / JWKS must be https (L2) -------------------------------


def test_factory_oidc_rejects_http_jwks(monkeypatch: pytest.MonkeyPatch):
    from managed_agents_mcp.app.auth.factory import AuthConfigError, build_authenticator

    monkeypatch.setenv("MCP_AUTH_MODE", "oidc")
    monkeypatch.setenv("MCP_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("MCP_OIDC_JWKS_URL", "http://issuer.example.com/jwks")  # plain http
    monkeypatch.setenv("MCP_OIDC_AUDIENCE", "client-1")
    with pytest.raises(AuthConfigError):
        build_authenticator()


def test_factory_oidc_allows_http_for_localhost(monkeypatch: pytest.MonkeyPatch):
    from managed_agents_mcp.app.auth.factory import build_authenticator

    monkeypatch.setenv("MCP_AUTH_MODE", "oidc")
    monkeypatch.setenv("MCP_OIDC_ISSUER", "http://localhost:8080")
    monkeypatch.setenv("MCP_OIDC_JWKS_URL", "http://localhost:8080/jwks")
    monkeypatch.setenv("MCP_OIDC_AUDIENCE", "client-1")
    assert build_authenticator() is not None


# ---- network transports fail closed without inbound auth (H1) ----------------


def test_network_transport_fails_closed_without_auth(monkeypatch: pytest.MonkeyPatch):
    from managed_agents_mcp.app.run import _require_inbound_auth

    monkeypatch.delenv("MCP_AUTH_MODE", raising=False)
    monkeypatch.delenv("MCP_ALLOW_INSECURE_NO_AUTH", raising=False)
    with pytest.raises(SystemExit):
        _require_inbound_auth()


def test_network_transport_allows_explicit_insecure_opt_out(monkeypatch: pytest.MonkeyPatch):
    from managed_agents_mcp.app.run import _require_inbound_auth

    monkeypatch.delenv("MCP_AUTH_MODE", raising=False)
    monkeypatch.setenv("MCP_ALLOW_INSECURE_NO_AUTH", "true")
    assert _require_inbound_auth() is None
