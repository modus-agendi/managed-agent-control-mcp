"""Generic OIDC (JWT) authenticator.

Validates `Authorization: Bearer <jwt>` against any OIDC provider — Auth0, Okta,
Keycloak, Microsoft Entra, AWS Cognito — by verifying the signature against the
provider's JWKS plus issuer / audience / expiry. This is the provider-agnostic
generalization of the imap server's Cognito-specific verifier: the Cognito-only
quirks (rejecting ID tokens via `token_use`, reading the audience from
`client_id`) are now opt-in config, not hardcoded.
"""

from __future__ import annotations

from collections.abc import Mapping

import jwt

from ..oauth_routes import protected_resource_route
from .base import Authenticator, AuthError, Principal, bearer_token

# Claims we'll try, in order, when building the Principal subject + matching the
# optional allow-list. Covers the common spellings across providers.
_PRINCIPAL_CLAIMS = ("sub", "username", "cognito:username", "email")


class OIDCAuthenticator(Authenticator):
    def __init__(
        self,
        *,
        issuer: str,
        jwks_url: str,
        audiences: list[str] | None = None,
        allowed_principals: list[str] | None = None,
        require_token_use: str | None = None,
        algorithms: list[str] | None = None,
    ) -> None:
        if not issuer or not jwks_url:
            raise ValueError("OIDCAuthenticator requires issuer and jwks_url")
        self._issuer = issuer
        self._jwks_url = jwks_url
        self._audiences = [a for a in (audiences or []) if a]
        self._allowed = [p.strip().lower() for p in (allowed_principals or []) if p.strip()]
        self._require_token_use = require_token_use or None
        self._algorithms = algorithms or ["RS256"]
        self._jwk_client: jwt.PyJWKClient | None = None

    def _client(self) -> jwt.PyJWKClient:
        # Cached per instance so warm requests reuse the in-process key cache
        # instead of re-fetching JWKS on every JWT-shaped request.
        if self._jwk_client is None:
            self._jwk_client = jwt.PyJWKClient(self._jwks_url)
        return self._jwk_client

    def validate(self, headers: Mapping[str, str], query: Mapping[str, str]) -> Principal:
        del query
        token = bearer_token(headers)
        # Only handle JWT-shaped tokens so a CompositeAuthenticator can fall
        # through to a static-bearer check for opaque tokens.
        if not token or not token.startswith("eyJ"):
            raise AuthError("no JWT bearer token")

        try:
            signing_key = self._client().get_signing_key_from_jwt(token)
            decoded = jwt.decode(
                token,
                signing_key.key,
                algorithms=self._algorithms,
                issuer=self._issuer,
                # Audience is checked manually below: access tokens carry it in
                # `client_id` (Cognito) rather than `aud`.
                options={"verify_aud": False},
            )
        except jwt.ExpiredSignatureError as e:
            raise AuthError(f"jwt expired: {e}") from e
        except jwt.InvalidIssuerError as e:
            raise AuthError(f"jwt issuer mismatch: {e}") from e
        except jwt.PyJWTError as e:
            raise AuthError(f"jwt invalid: {e}") from e
        except Exception as e:  # network / JWKS fetch / key-not-found
            raise AuthError(f"jwt verification error: {e}") from e

        self._check_token_use(decoded)
        self._check_audience(decoded)
        self._check_allowed(decoded)

        subject = next((str(decoded[c]) for c in _PRINCIPAL_CLAIMS if decoded.get(c)), "unknown")
        return Principal(subject=subject, email=decoded.get("email"), raw=decoded)

    def _check_token_use(self, decoded: dict) -> None:
        if self._require_token_use and decoded.get("token_use") != self._require_token_use:
            raise AuthError(
                f"jwt token_use {decoded.get('token_use')!r} != {self._require_token_use!r}"
            )

    def _check_audience(self, decoded: dict) -> None:
        if not self._audiences:
            return
        claim = decoded.get("client_id") or decoded.get("aud")
        claims = claim if isinstance(claim, list) else [claim]
        if not any(c in self._audiences for c in claims):
            raise AuthError(f"jwt audience {claim!r} not in {self._audiences}")

    def _check_allowed(self, decoded: dict) -> None:
        if not self._allowed:
            return
        candidates = {str(decoded[c]).lower() for c in _PRINCIPAL_CLAIMS if decoded.get(c)}
        if candidates.isdisjoint(self._allowed):
            raise AuthError(f"jwt principal {sorted(candidates)} not in allow-list")

    def public_paths(self) -> tuple[str, ...]:
        return ("/.well-known/",)

    def routes(self):
        # Advertise the provider itself as the authorization server; compliant
        # clients then fetch the provider's own discovery + endpoints.
        return [protected_resource_route(authorization_servers=[self._issuer])]
