"""Zero-trust properties of the shared HTTP client."""

import httpx2 as httpx
import pytest
from pydantic import SecretStr

from govcon_mcp.errors import EgressDenied, UpstreamError
from govcon_mcp.http import SafeClient

pytestmark = pytest.mark.anyio


def client(handler, **kw):
    return SafeClient("test", {"api.example.gov"}, transport=httpx.MockTransport(handler), cache_ttl_s=kw.pop("ttl", 0),
                      **kw)


async def test_denies_non_allowlisted_host_and_plain_http():
    c = client(lambda r: httpx.Response(200, json={}))
    for url in ("https://evil.example.com/x", "http://api.example.gov/x", "https://user:pw@api.example.gov/x",
                "https://api.example.gov.evil.com/x"):
        with pytest.raises(EgressDenied):
            await c.get_json(url)


async def test_refuses_redirects():
    c = client(lambda r: httpx.Response(302, headers={"location": "https://evil.example.com/"}))
    with pytest.raises(UpstreamError, match="redirect refused"):
        await c.get_json("https://api.example.gov/x")


async def test_secret_injected_but_redacted_from_errors_and_body():
    seen = {}

    def handler(r):
        seen["url"] = str(r.url)
        if "boom" in str(r.url):
            return httpx.Response(400, json={"error": f"bad key {r.url.params['api_key']}"})
        return httpx.Response(200, json={"self": f"https://api.example.gov/x?api_key={r.url.params['api_key']}"})

    c = client(handler, secret_params={"api_key": SecretStr("TOPSECRET")})
    body = await c.get_json("https://api.example.gov/x")
    assert "TOPSECRET" in seen["url"]  # sent upstream
    assert "TOPSECRET" not in str(body)  # never returned to the model
    with pytest.raises(UpstreamError) as exc:
        await c.get_json("https://api.example.gov/boom")
    assert "TOPSECRET" not in str(exc.value)


async def test_response_size_cap():
    c = client(lambda r: httpx.Response(200, content=b"[" + b"1," * 1000 + b"1]",
                                        headers={"content-type": "application/json"}), max_bytes=100)
    with pytest.raises(UpstreamError, match="exceeded"):
        await c.get_json("https://api.example.gov/x")


async def test_rejects_non_json():
    c = client(lambda r: httpx.Response(200, text="<html>", headers={"content-type": "text/html"}))
    with pytest.raises(UpstreamError, match="content-type"):
        await c.get_json("https://api.example.gov/x")


async def test_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def no_sleep(_):
        return None

    monkeypatch.setattr("govcon_mcp.http.asyncio.sleep", no_sleep)

    def handler(r):
        calls["n"] += 1
        return httpx.Response(503, json={}) if calls["n"] < 3 else httpx.Response(200, json={"ok": True})

    c = client(handler, rate_per_s=1000, burst=1000)
    assert await c.get_json("https://api.example.gov/x") == {"ok": True}
    assert calls["n"] == 3


async def test_cache_dedupes_and_excludes_secret(monkeypatch):
    calls = {"n": 0}

    def handler(r):
        calls["n"] += 1
        return httpx.Response(200, json={"n": calls["n"]})

    c = client(handler, ttl=60, secret_params={"api_key": SecretStr("K")})
    a = await c.get_json("https://api.example.gov/x", {"q": "1"})
    b = await c.get_json("https://api.example.gov/x", {"q": "1"})
    assert a == b and calls["n"] == 1
    assert all("K" not in k for k in c._cache._data)  # noqa: SLF001
