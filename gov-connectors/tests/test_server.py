import pytest

from govcon_mcp.server import _http_kwargs


def test_non_loopback_without_oauth_refuses(monkeypatch):
    for var in ("GOVCON_OAUTH_ISSUER", "GOVCON_PUBLIC_URL", "GOVCON_OAUTH_JWKS_URL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit):
        _http_kwargs("0.0.0.0", 8000)


def test_loopback_without_oauth_allowed_with_dns_rebinding_protection(monkeypatch):
    monkeypatch.delenv("GOVCON_OAUTH_ISSUER", raising=False)
    kw = _http_kwargs("127.0.0.1", 8000)
    ts = kw["run"]["transport_security"]
    assert ts.enable_dns_rebinding_protection and "127.0.0.1:8000" in ts.allowed_hosts
    assert "token_verifier" not in kw["server"]


def test_oauth_configured_enables_verifier(monkeypatch):
    monkeypatch.setenv("GOVCON_OAUTH_ISSUER", "https://idp.example.gov")
    monkeypatch.setenv("GOVCON_PUBLIC_URL", "https://govcon.example.gov/mcp")
    monkeypatch.setenv("GOVCON_OAUTH_JWKS_URL", "https://idp.example.gov/jwks")
    kw = _http_kwargs("0.0.0.0", 8000)
    assert kw["server"]["token_verifier"] and kw["server"]["auth"]
