"""One connector per server: tool, secret and scope isolation."""

import shutil
import sys

import pytest
from pydantic import SecretStr

from govcon_mcp.config import Settings
from govcon_mcp.server import SOURCES, _http_kwargs, build_server

pytestmark = pytest.mark.anyio

PREFIX = {"usaspending": "usaspending_", "sam": "sam_", "calc": "calc_", "sbir": "sbir_", "tango": "tango_",
          "sled": "sled_"}


@pytest.fixture
def all_keys(monkeypatch):
    monkeypatch.setenv("SAM_API_KEY", "SAMKEY-AAA")
    monkeypatch.setenv("TANGO_API_KEY", "TANGOKEY-BBB")
    monkeypatch.setenv("SOCRATA_APP_TOKEN", "SODATOKEN-CCC")


@pytest.mark.parametrize("source", list(SOURCES))
async def test_each_server_exposes_only_its_own_tools(all_keys, source):
    server = build_server(source=source)
    names = {t.name for t in await server.list_tools()}
    own = {n for n in names if n.startswith(PREFIX[source])}
    assert own, f"{source} registered no tools"
    assert names - own == {"govcon_connection_status"}, f"{source} leaks: {names - own}"
    assert server.name == f"govcon-{source}"


@pytest.mark.parametrize("source", list(SOURCES))
def test_each_server_loads_only_its_own_secret(all_keys, source):
    s = Settings.from_env(only=source)
    loaded = {k for k, v in (("sam", s.sam_api_key), ("tango", s.tango_api_key), ("sled", s.socrata_app_token)) if v}
    assert loaded <= {source}, f"{source} server loaded other secrets: {loaded - {source}}"


def test_single_source_refuses_wider_settings():
    wide = Settings(sam_api_key=SecretStr("k"), tango_api_key=SecretStr("t"))  # enables every connector
    with pytest.raises(ValueError, match="only 'sam'"):
        build_server(wide, source="sam")
    with pytest.raises(ValueError, match="unknown source"):
        build_server(source="fpds")


def test_missing_key_server_still_explains_itself(monkeypatch):
    monkeypatch.delenv("SAM_API_KEY", raising=False)
    monkeypatch.delenv("SAM_API_KEY_FILE", raising=False)
    server = build_server(source="sam")
    import anyio

    names = anyio.run(lambda: server.list_tools())
    assert {t.name for t in names} == {"govcon_connection_status"}


def test_default_oauth_scope_is_per_source(monkeypatch):
    monkeypatch.setenv("GOVCON_OAUTH_ISSUER", "https://idp.example.gov")
    monkeypatch.setenv("GOVCON_PUBLIC_URL", "https://sam.govcon.example.gov/mcp")
    monkeypatch.setenv("GOVCON_OAUTH_JWKS_URL", "https://idp.example.gov/jwks")
    monkeypatch.delenv("GOVCON_OAUTH_SCOPES", raising=False)
    kw = _http_kwargs("0.0.0.0", 8002, "govcon.sam.read")
    assert kw["server"]["token_verifier"].required_scopes == {"govcon.sam.read"}


def test_default_ports_are_distinct():
    ports = [s.port for s in SOURCES.values()]
    assert len(ports) == len(set(ports))


@pytest.mark.parametrize("source", ["usaspending", "calc", "sled"])
async def test_console_script_runs_as_separate_stdio_server(source):
    """Spawn the real installed command and list its tools over the MCP stdio protocol."""
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    exe = shutil.which(f"govcon-{source}")
    if exe is None:
        pytest.skip("package not installed (pip install -e .)")
    params = StdioServerParameters(command=exe, env={"GOVCON_LOG_LEVEL": "WARNING"})
    with open("/dev/null", "w") if sys.platform != "win32" else open("NUL", "w") as devnull:
        async with stdio_client(params, errlog=devnull) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                init = await session.initialize()
                tools = await session.list_tools()
    assert init.server_info.name == f"govcon-{source}"
    names = {t.name for t in tools.tools}
    assert all(n.startswith(PREFIX[source]) or n == "govcon_connection_status" for n in names), names
