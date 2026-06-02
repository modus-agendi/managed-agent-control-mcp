"""Security: the OIDC JWT verifier against forged / malformed / wrong tokens.

Each test wires a known RSA public key into the authenticator (bypassing the
network JWKS fetch) and asserts that anything not a valid, correctly-signed,
in-policy token is rejected with AuthError.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from managed_agents_mcp.app.auth.base import AuthError
from managed_agents_mcp.app.auth.oidc import OIDCAuthenticator


def _b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _forge_hs256(payload: dict, secret: bytes) -> str:
    """Hand-craft an HS256 JWT (PyJWT refuses to encode HMAC with a PEM key, which
    is exactly the mitigation under test — so an attacker would build it by hand)."""
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps(payload).encode())
    signing_input = header + b"." + body
    sig = _b64(hmac.new(secret, signing_input, hashlib.sha256).digest())
    return (signing_input + b"." + sig).decode()


ISSUER = "https://issuer.example.com"
AUD = "client-1"


@pytest.fixture(scope="module")
def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _authenticator(public_key, **kw) -> OIDCAuthenticator:
    auth = OIDCAuthenticator(issuer=ISSUER, jwks_url="https://x/jwks", audiences=[AUD], **kw)
    auth._jwk_client = SimpleNamespace(  # type: ignore[attr-defined]
        get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=public_key)
    )
    return auth


def _sign(private_key, alg: str = "RS256", **claims) -> str:
    payload = {
        "iss": ISSUER,
        "aud": AUD,
        "client_id": AUD,
        "sub": "user-1",
        "exp": int(time.time()) + 3600,
        **claims,
    }
    return jwt.encode(payload, private_key, algorithm=alg)


def _hdr(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def test_valid_token_accepted(keypair):
    auth = _authenticator(keypair.public_key())
    assert auth.validate(_hdr(_sign(keypair)), {}).subject == "user-1"


def test_alg_none_rejected(keypair):
    auth = _authenticator(keypair.public_key())
    forged = jwt.encode({"iss": ISSUER, "sub": "x", "aud": AUD}, "", algorithm="none")
    with pytest.raises(AuthError):
        auth.validate(_hdr(forged), {})


def test_hs256_key_confusion_rejected(keypair):
    # Classic attack: sign HS256 using the *public* key as the shared secret and
    # hope the verifier treats it as symmetric. We only allow RS256, so reject.
    pub_pem = keypair.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    forged = _forge_hs256({"iss": ISSUER, "sub": "x", "aud": AUD, "client_id": AUD}, pub_pem)
    auth = _authenticator(keypair.public_key())
    with pytest.raises(AuthError):
        auth.validate(_hdr(forged), {})


def test_tampered_payload_rejected(keypair):
    token = _sign(keypair)
    head, payload, sig = token.split(".")
    tampered = f"{head}.{payload[:-2] + ('AA' if payload[-2:] != 'AA' else 'BB')}.{sig}"
    auth = _authenticator(keypair.public_key())
    with pytest.raises(AuthError):
        auth.validate(_hdr(tampered), {})


def test_wrong_signing_key_rejected(keypair, other_key):
    token = _sign(other_key)  # signed by a key the server doesn't trust
    auth = _authenticator(keypair.public_key())
    with pytest.raises(AuthError):
        auth.validate(_hdr(token), {})


def test_expired_rejected(keypair):
    auth = _authenticator(keypair.public_key())
    with pytest.raises(AuthError):
        auth.validate(_hdr(_sign(keypair, exp=int(time.time()) - 10)), {})


def test_wrong_issuer_rejected(keypair):
    auth = _authenticator(keypair.public_key())
    with pytest.raises(AuthError):
        auth.validate(_hdr(_sign(keypair, iss="https://evil.example.com")), {})


def test_wrong_audience_rejected(keypair):
    auth = _authenticator(keypair.public_key())
    with pytest.raises(AuthError):
        auth.validate(_hdr(_sign(keypair, client_id="someone-else", aud="someone-else")), {})


def test_token_use_enforced(keypair):
    auth = _authenticator(keypair.public_key(), require_token_use="access")
    with pytest.raises(AuthError):
        auth.validate(_hdr(_sign(keypair, token_use="id")), {})
    # access token passes
    assert auth.validate(_hdr(_sign(keypair, token_use="access")), {}).subject == "user-1"


def test_principal_allowlist(keypair):
    auth = _authenticator(keypair.public_key(), allowed_principals=["alice@example.com"])
    with pytest.raises(AuthError):
        auth.validate(_hdr(_sign(keypair, email="bob@example.com")), {})
    ok = auth.validate(_hdr(_sign(keypair, email="alice@example.com")), {})
    assert ok.email == "alice@example.com"


@pytest.mark.parametrize(
    "header", [{}, {"authorization": "Basic abc"}, {"authorization": "Bearer "}]
)
def test_missing_or_malformed_header_rejected(keypair, header):
    auth = _authenticator(keypair.public_key())
    with pytest.raises(AuthError):
        auth.validate(header, {})
