"""Bearer-token verification for the remote (streamable-HTTP) deployment.

Zero trust: when the server listens on anything other than loopback, every
request must carry a JWT issued by the configured OAuth issuer, signed with a
key from its JWKS (asymmetric algorithms only), unexpired, and with ``aud``
equal to this server's public URL. There is no shared static token mode.
"""

from __future__ import annotations

import anyio
import jwt
from mcp.server.auth.provider import AccessToken

ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"]


class JWTVerifier:
    def __init__(self, *, issuer: str, audience: str, jwks_url: str, required_scopes: list[str] | None = None) -> None:
        if not jwks_url.startswith("https://"):
            raise ValueError("GOVCON_OAUTH_JWKS_URL must be https")
        self.issuer, self.audience = issuer, audience
        self.required_scopes = set(required_scopes or [])
        self._jwks = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600, timeout=10)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            key = await anyio.to_thread.run_sync(self._jwks.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token, key.key, algorithms=ALGORITHMS, audience=self.audience, issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]}, leeway=30,
            )
        except (jwt.PyJWTError, OSError):
            return None
        scopes = set((claims.get("scope") or "").split()) | set(claims.get("scp") or [])
        if not self.required_scopes.issubset(scopes):
            return None
        return AccessToken(
            token=token, client_id=str(claims.get("azp") or claims.get("client_id") or claims["sub"]),
            scopes=sorted(scopes), expires_at=int(claims["exp"]), resource=self.audience,
            subject=str(claims["sub"]), claims={"iss": claims["iss"]},
        )
