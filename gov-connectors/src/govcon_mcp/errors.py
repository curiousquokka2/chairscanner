"""Error types. Messages are safe to surface to the model (secrets are redacted upstream).

Subclassing ``ToolError`` makes the SDK return our message as a tool error; any
other exception becomes a generic error, so stack traces/internals never leak.
"""

from mcp.server.mcpserver.exceptions import ToolError


class GovconError(ToolError):
    """Base class for errors returned to tool callers."""


class EgressDenied(GovconError):
    """A request targeted a host outside the connector's allowlist."""


class InvalidInput(GovconError):
    """Tool input failed validation."""


class UpstreamError(GovconError):
    def __init__(self, service: str, status: int, detail: str) -> None:
        self.service, self.status, self.detail = service, status, detail
        hint = ""
        if status in (401, 403):
            hint = " (check the API key for this service - see docs/CONNECTIONS.md)"
        elif status == 429:
            hint = " (rate limit reached - SAM.gov personal keys may allow only 10 calls/day)"
        super().__init__(f"{service} returned HTTP {status}: {detail[:300]}{hint}")
