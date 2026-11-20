"""Controls added in the hardening pass. Each has a negative AND a positive case."""

import time

import httpx2 as httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from govcon_mcp.auth import JWTVerifier
from govcon_mcp.config import Settings
from govcon_mcp.errors import UpstreamError
from govcon_mcp.safehttp import SafeClient
from govcon_mcp.server import build_server

from .conftest import call

pytestmark = pytest.mark.anyio


# ---- daily quota budget -------------------------------------------------
async def test_daily_budget_blocks_after_limit_and_cache_hits_are_free():
    calls = {"n": 0}

    def handler(r):
        calls["n"] += 1
        return httpx.Response(200, json={"n": calls["n"]})

    c = SafeClient("sam", {"api.example.gov"}, transport=httpx.MockTransport(handler), cache_ttl_s=60, daily_budget=2)
    await c.get_json("https://api.example.gov/a")
    await c.get_json("https://api.example.gov/a")  # cache hit: no budget used
    await c.get_json("https://api.example.gov/b")
    with pytest.raises(UpstreamError, match="daily budget"):
        await c.get_json("https://api.example.gov/c")
    assert calls["n"] == 2


async def test_sam_connector_wires_default_budget(make_server):
    server, rec = make_server({"opportunities": {"opportunitiesData": []}},
                              settings=Settings(sam_api_key=SecretStr("k"), cache_ttl_s=0, sam_daily_budget=1))
    err, _ = await call(server, "sam_search_opportunities", {"naics": "541512"})
    assert not err
    err, out = await call(server, "sam_search_opportunities", {"naics": "541511"})
    assert err and "daily budget" in str(out) and len(rec.requests) == 1


def test_budget_env_parsing(monkeypatch):
    monkeypatch.setenv("GOVCON_SAM_DAILY_BUDGET", "none")
    assert Settings.from_env().sam_daily_budget is None
    monkeypatch.setenv("GOVCON_SAM_DAILY_BUDGET", "0")
    with pytest.raises(ValueError):
        Settings.from_env()
    monkeypatch.delenv("GOVCON_SAM_DAILY_BUDGET")
    assert Settings.from_env().sam_daily_budget == 10


# ---- path-segment IDs ---------------------------------------------------
@pytest.mark.parametrize("bad", ["...", ".hidden", "a..b", "x/y", "a%2Fb"])
async def test_tango_record_id_rejects_dot_tricks(make_server, bad):
    server, rec = make_server()
    err, _ = await call(server, "tango_get", {"resource": "contracts", "record_id": bad})
    assert err and not rec.requests


async def test_tango_record_id_accepts_uuid(make_server):
    server, rec = make_server({"/api/contracts/": {"piid": "X"}})
    err, _ = await call(server, "tango_get", {"resource": "contracts",
                                              "record_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"})
    assert not err and rec.last.url.path == "/api/contracts/3fa85f64-5717-4562-b3fc-2c963f66afa6/"


# ---- JWT: alg=none ------------------------------------------------------
async def test_alg_none_rejected(monkeypatch):
    v = JWTVerifier(issuer="https://i.gov", audience="https://a.gov/mcp", jwks_url="https://i.gov/jwks")
    monkeypatch.setattr(v._jwks, "get_signing_key_from_jwt",  # noqa: SLF001
                        lambda t: type("K", (), {"key": rsa.generate_private_key(65537, 2048).public_key()})())
    unsigned = jwt.encode({"iss": "https://i.gov", "aud": "https://a.gov/mcp", "sub": "x", "iat": 1,
                           "exp": 2**31}, None, algorithm="none")
    assert await v.verify_token(unsigned) is None


# ---- end-to-end HTTP auth (negative AND positive through the real ASGI stack) ----
ISS, AUD = "https://idp.example.gov", "http://127.0.0.1:8000/mcp"
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "t", "version": "0"}}}
HDRS = {"accept": "application/json, text/event-stream", "content-type": "application/json",
        "host": "127.0.0.1:8000"}


@pytest.fixture
def http_app(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("GOVCON_OAUTH_ISSUER", ISS)
    monkeypatch.setenv("GOVCON_PUBLIC_URL", AUD)
    monkeypatch.setenv("GOVCON_OAUTH_JWKS_URL", f"{ISS}/jwks")
    monkeypatch.delenv("GOVCON_OAUTH_SCOPES", raising=False)
    from govcon_mcp.server import _http_kwargs

    kw = _http_kwargs("127.0.0.1", 8000)
    verifier = kw["server"]["token_verifier"]
    monkeypatch.setattr(verifier._jwks, "get_signing_key_from_jwt",  # noqa: SLF001
                        lambda t: type("K", (), {"key": key.public_key()})())
    server = build_server(Settings(cache_ttl_s=0), **kw["server"])
    run = kw["run"]
    app = server.streamable_http_app(stateless_http=True, json_response=True,
                                     transport_security=run["transport_security"], host="127.0.0.1")

    def mint(scope="govcon.read"):
        now = int(time.time())
        return jwt.encode({"iss": ISS, "aud": AUD, "sub": "u1", "iat": now, "exp": now + 300, "scope": scope},
                          key, algorithm="RS256")
    return app, mint


async def _post(app, headers, path="/mcp", body=INIT, method="POST"):
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as c:
            if method == "GET":
                return await c.get(path, headers=headers)
            return await c.post(path, json=body, headers=headers)


async def test_http_rejects_missing_token(http_app):
    app, _ = http_app
    assert (await _post(app, HDRS)).status_code == 401


async def test_http_rejects_wrong_scope(http_app):
    app, mint = http_app
    r = await _post(app, {**HDRS, "authorization": f"Bearer {mint('other.scope')}"})
    assert r.status_code in (401, 403)


async def test_http_accepts_valid_token(http_app):
    app, mint = http_app
    r = await _post(app, {**HDRS, "authorization": f"Bearer {mint()}"})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["serverInfo"]["name"] == "govcon-connectors"


async def test_http_rejects_foreign_host_header(http_app):
    app, mint = http_app
    r = await _post(app, {**HDRS, "host": "evil.example.com", "authorization": f"Bearer {mint()}"})
    assert r.status_code in (400, 421)


async def test_healthz_is_public_and_minimal(http_app):
    app, _ = http_app
    r = await _post(app, {"host": "127.0.0.1:8000"}, path="/healthz", method="GET")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


# ---- terms-of-use and outage handling (added after reading each provider's terms, 2026-11-20) ----
async def test_chicago_results_carry_required_disclaimer(make_server):
    server, _ = make_server({"rsxa-ify5": [{"vendor_name": "V"}]})
    err, out = await call(server, "sled_query", {"dataset": "chicago_contracts"})
    assert not err and any("City of Chicago makes no claims" in n for n in out["notes"])


async def test_sbir_403_explains_maintenance_not_key(make_server):
    server, _ = make_server({"public/api/awards": httpx.Response(403, json={"message": "Forbidden"})})
    err, out = await call(server, "sbir_search_awards", {"agency": "NSF"})
    assert err and "undergoing maintenance" in str(out) and "API key" not in str(out)


async def test_keyed_service_403_still_hints_key(make_server):
    server, _ = make_server({"opportunities": httpx.Response(403, json={"error": "bad key"})})
    err, out = await call(server, "sam_search_opportunities", {"naics": "541512"})
    assert err and "check the API key" in str(out)


async def test_tango_page_cap_and_terms_note(make_server):
    server, rec = make_server({"/api/contracts/": {"count": 0, "results": []}})
    err, _ = await call(server, "tango_search", {"resource": "contracts", "page": 21})
    assert err and not rec.requests
    err, out = await call(server, "tango_search", {"resource": "contracts", "page": 20})
    assert not err and "tango.makegov.com/terms" in out["notes"][0]


async def test_retry_error_redacts_before_truncating(monkeypatch):
    async def no_sleep(_):
        return None
    monkeypatch.setattr("govcon_mcp.safehttp.asyncio.sleep", no_sleep)
    key = "K" * 40
    body = "x" * 280 + key  # key straddles the 300-char cut
    c = SafeClient("sam", {"api.example.gov"}, secret_params={"api_key": SecretStr(key)}, cache_ttl_s=0,
                   rate_per_s=1000, burst=1000, max_retries=1,
                   transport=httpx.MockTransport(lambda r: httpx.Response(503, text=body,
                                                                          headers={"content-type": "text/plain"})))
    with pytest.raises(UpstreamError) as exc:
        await c.get_json("https://api.example.gov/x")
    assert "KKKKK" not in str(exc.value)


# ---- secrets never reach logs, even at DEBUG ----
async def test_api_key_scrubbed_from_http_client_logs_at_debug(make_server, caplog):
    import logging
    server, _ = make_server({"opportunities": {"opportunitiesData": []}})
    logging.getLogger("httpx2").setLevel(logging.DEBUG)  # simulate an operator turning debug on
    try:
        with caplog.at_level(logging.DEBUG):
            err, _ = await call(server, "sam_search_opportunities", {"naics": "541512"})
            logging.getLogger("httpx2").info("HTTP Request: GET https://api.sam.gov/x?api_key=%s", "SAMSECRET123")
    finally:
        logging.getLogger("httpx2").setLevel(logging.WARNING)
    assert not err
    assert caplog.records, "expected log records"
    assert "SAMSECRET123" not in caplog.text


async def test_austin_and_texas_results_carry_attribution(make_server):
    server, _ = make_server({"3ebq-e9iz": [{"lgl_nm": "V"}], "svjm-sdfz": [{"vendor_name_description": "V"}]})
    for ds, needle in (("austin_po_commodity_lines", "City of Austin"), ("texas_tceq_contracts", "Texas Commission")):
        err, out = await call(server, "sled_query", {"dataset": ds})
        assert not err and any(needle in n and "Attribution" in n for n in out["notes"]), ds
