"""Runtime configuration.

Secrets are read from the environment (or from ``<NAME>_FILE`` paths, the
Docker/Kubernetes secrets convention) once at start-up, wrapped in
``SecretStr`` so they never appear in ``repr``/logs, and handed only to the
connector that needs them. Nothing here is ever returned to a tool caller.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import SecretStr

# Every connector the server knows about. Used to validate GOVCON_ENABLED.
ALL_CONNECTORS = ("usaspending", "sam", "calc", "sbir", "tango", "sled")


def _read_secret(name: str) -> SecretStr | None:
    """Return a secret from ``$NAME`` or the file at ``$NAME_FILE``; None if unset."""
    file_path = os.environ.get(f"{name}_FILE")
    if file_path:
        value = Path(file_path).read_text(encoding="utf-8").strip()
    else:
        value = os.environ.get(name, "").strip()
    return SecretStr(value) if value else None


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    sam_api_key: SecretStr | None = None
    tango_api_key: SecretStr | None = None
    socrata_app_token: SecretStr | None = None
    tango_base_url: str = "https://tango.makegov.com"
    enabled: frozenset[str] = field(default_factory=lambda: frozenset(ALL_CONNECTORS))
    http_timeout_s: float = 30.0
    cache_ttl_s: float = 900.0  # 15 min; SAM keys can be capped at 10 calls/day
    max_response_bytes: int = 8 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Settings":
        enabled_raw = os.environ.get("GOVCON_ENABLED", "")
        enabled = (
            frozenset(x.strip().lower() for x in enabled_raw.split(",") if x.strip())
            if enabled_raw
            else frozenset(ALL_CONNECTORS)
        )
        unknown = enabled - set(ALL_CONNECTORS)
        if unknown:
            raise ValueError(f"GOVCON_ENABLED has unknown connectors: {sorted(unknown)}")
        return cls(
            sam_api_key=_read_secret("SAM_API_KEY"),
            tango_api_key=_read_secret("TANGO_API_KEY"),
            socrata_app_token=_read_secret("SOCRATA_APP_TOKEN"),
            tango_base_url=os.environ.get("TANGO_BASE_URL", cls.tango_base_url),
            enabled=enabled,
            http_timeout_s=_float("GOVCON_HTTP_TIMEOUT", cls.http_timeout_s),
            cache_ttl_s=_float("GOVCON_CACHE_TTL", cls.cache_ttl_s),
        )
