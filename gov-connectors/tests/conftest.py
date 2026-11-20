import json

import httpx2 as httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import SecretStr

from govcon_mcp.config import Settings
from govcon_mcp.server import build_server


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Recorder:
    """MockTransport that records requests and replays canned responses by path substring."""

    def __init__(self, routes: dict[str, object] | None = None):
        self.routes = routes or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for needle, resp in self.routes.items():
            if needle in str(request.url):
                if callable(resp):
                    return resp(request)
                if isinstance(resp, httpx.Response):
                    return resp
                return httpx.Response(200, json=resp)
        return httpx.Response(404, json={"detail": "no mock route"})

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


SETTINGS = Settings(sam_api_key=SecretStr("SAMSECRET123"), tango_api_key=SecretStr("TANGOSECRET456"),
                    cache_ttl_s=0)


@pytest.fixture
def make_server():
    def _make(routes=None, settings=SETTINGS):
        rec = Recorder(routes)
        server = build_server(settings, transport=httpx.MockTransport(rec))
        return server, rec
    return _make


async def call(server, name, args=None):
    """Call a tool and return (is_error, payload-dict-or-text)."""
    try:
        result = await server.call_tool(name, args or {})
    except ToolError as exc:  # in-process calls raise; over the wire this becomes isError=true
        return True, str(exc)
    text = result.content[0].text if result.content else ""
    try:
        return result.is_error, json.loads(text)
    except ValueError:
        return result.is_error, text
