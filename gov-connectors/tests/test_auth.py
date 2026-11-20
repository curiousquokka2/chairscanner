"""JWT verifier for remote HTTP deployments."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from govcon_mcp.auth import JWTVerifier

pytestmark = pytest.mark.anyio

ISS, AUD = "https://idp.example.gov", "https://govcon.example.gov/mcp"


@pytest.fixture
def keys():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def verifier(keys, monkeypatch):
    v = JWTVerifier(issuer=ISS, audience=AUD, jwks_url="https://idp.example.gov/jwks", required_scopes=["govcon.read"])

    class _Key:
        key = keys.public_key()

    monkeypatch.setattr(v._jwks, "get_signing_key_from_jwt", lambda token: _Key())  # noqa: SLF001
    return v


def token(keys, **overrides):
    now = int(time.time())
    claims = {"iss": ISS, "aud": AUD, "sub": "user-1", "iat": now, "exp": now + 300, "scope": "govcon.read"}
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, keys, algorithm="RS256")


async def test_valid_token(verifier, keys):
    at = await verifier.verify_token(token(keys))
    assert at and at.subject == "user-1" and "govcon.read" in at.scopes


@pytest.mark.parametrize("override", [
    {"aud": "https://other.example.gov"}, {"iss": "https://evil.example.com"},
    {"exp": int(time.time()) - 3600}, {"scope": "other"}, {"sub": None},
])
async def test_rejects_bad_claims(verifier, keys, override):
    assert await verifier.verify_token(token(keys, **override)) is None


async def test_rejects_hs256_and_foreign_key(verifier, keys):
    forged = jwt.encode({"iss": ISS, "aud": AUD, "sub": "x", "iat": 1, "exp": 2**31}, "secret", algorithm="HS256")
    assert await verifier.verify_token(forged) is None
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert await verifier.verify_token(token(other)) is None


def test_jwks_must_be_https():
    with pytest.raises(ValueError):
        JWTVerifier(issuer=ISS, audience=AUD, jwks_url="http://idp.example.gov/jwks")
