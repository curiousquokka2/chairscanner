"""Connector base class.

A connector owns exactly one ``SafeClient`` (its own allowlist and secrets -
no shared credentials) and registers read-only tools on the MCP server.
"""

from __future__ import annotations

from mcp_types import ToolAnnotations

from ..config import Settings
from ..http import SafeClient

# Every tool in this server is read-only and talks to an external system.
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)


class Connector:
    name: str = ""
    hosts: frozenset[str] = frozenset()
    #: Name of the setting that must be present for the connector to load (None = no key needed).
    requires: str | None = None

    def __init__(self, settings: Settings, transport=None) -> None:
        self.settings = settings
        self.client: SafeClient = self.build_client(transport)

    @classmethod
    def available(cls, settings: Settings) -> tuple[bool, str]:
        if cls.name not in settings.enabled:
            return False, "disabled via GOVCON_ENABLED"
        if cls.requires and getattr(settings, cls.requires) is None:
            return False, f"missing {cls.requires.upper()} (human action required - see docs/CONNECTIONS.md)"
        return True, "ready"

    def build_client(self, transport=None) -> SafeClient:  # pragma: no cover - overridden
        raise NotImplementedError

    def register(self, mcp) -> None:  # pragma: no cover - overridden
        raise NotImplementedError
