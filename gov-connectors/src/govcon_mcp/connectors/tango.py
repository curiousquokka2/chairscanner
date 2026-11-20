"""Tango (MakeGov) API - aggregated federal + SLED contracting data. Requires ``TANGO_API_KEY``.

Docs: https://docs.makegov.com/api-reference/   Swagger: https://tango.dev/api/
Tango fills gaps the official APIs do not cover well: SLED solicitations and
forecasts, agency forecasts, GAO/COFC protests, SBIR topics, IDV vehicles,
DIBBS, Federal Register. Resources are allowlisted; free-form paths are not.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field

from ..errors import InvalidInput
from ..safehttp import SafeClient
from ..validation import clean_text, envelope
from .base import READ_ONLY, Connector

ALLOWED_BASES = frozenset({"tango.makegov.com", "tango.dev"})

TERMS_NOTE = ("Tango Terms of Service: data may be shown to people outside your organisation only with each "
              "record linked to its public source or Tango, and never as bulk exports. Do not page through "
              "whole datasets. https://tango.makegov.com/terms/")

RESOURCES: dict[str, str] = {
    "contracts": "/api/contracts/",
    "idvs": "/api/idvs/",
    "vehicles": "/api/vehicles/",
    "subawards": "/api/subawards/",
    "otas": "/api/otas/",
    "opportunities": "/api/opportunities/",
    "forecasts": "/api/forecasts/",
    "grants": "/api/grants/",
    "entities": "/api/entities/",
    "exclusions": "/api/exclusions/",
    "protests": "/api/protests/",
    "sbir_topics": "/api/sbir/topics/",
    "sbir_solicitations": "/api/sbir/solicitations/",
    "sled_opportunities": "/api/sled/opportunities/",
    "sled_forecasts": "/api/sled/forecasts/",
}
Resource = Literal[tuple(RESOURCES)]  # type: ignore[valid-type]

FilterKey = Annotated[str, Field(pattern=r"^[a-z][a-z_]{1,40}$")]
_TANGO_UNSAFE = re.compile(r"[&{}^\\\x00-\x1f]")
FilterVal = Annotated[str, Field(min_length=1, max_length=200)]


class Tango(Connector):
    name = "tango"
    requires = "tango_api_key"

    def __init__(self, settings, transport=None) -> None:
        host = (urlsplit(settings.tango_base_url).hostname or "").lower()
        if urlsplit(settings.tango_base_url).scheme != "https" or host not in ALLOWED_BASES:
            raise ValueError(f"TANGO_BASE_URL must be https on one of {sorted(ALLOWED_BASES)}")
        self.base = f"https://{host}"
        self.hosts = frozenset({host})
        super().__init__(settings, transport)

    def build_client(self, transport=None) -> SafeClient:
        return SafeClient(self.name, self.hosts, secret_headers={"X-API-KEY": self.settings.tango_api_key},
                          rate_per_s=2, burst=4, timeout_s=self.settings.http_timeout_s,
                          daily_budget=self.settings.tango_daily_budget,
                          cache_ttl_s=self.settings.cache_ttl_s, transport=transport)

    def register(self, mcp) -> None:
        client, base = self.client, self.base

        @mcp.tool(annotations=READ_ONLY, description=(
            "Query Tango (MakeGov) aggregated contracting data. resource is one of: "
            + ", ".join(RESOURCES) + ". `filters` are resource-specific query params per Tango docs "
            "(e.g. sled_opportunities: state=TX, status=open|unknown, jurisdiction=local, category_code, "
            "first_seen_after=YYYY-MM-DD; opportunities: naics, psc, set_aside, agency). SLED results are "
            "partial coverage - call tango_sled_coverage before treating a state count as market size."))
        async def tango_search(
            resource: Resource,
            search: Annotated[str | None, Field(min_length=2, max_length=200)] = None,
            filters: Annotated[dict[FilterKey, FilterVal] | None, Field(max_length=15)] = None,
            ordering: Annotated[str | None, Field(pattern=r"^-?[a-z_]{2,40}$")] = None,
            # Tango Terms 3(c): systematic paging to copy a dataset needs an Order Form. Cap pages to
            # keep agents on targeted queries (20 pages x 100 = 2,000 records per query).
            page: Annotated[int, Field(ge=1, le=20)] = 1,
            limit: Annotated[int, Field(ge=1, le=100)] = 25,
        ) -> dict:
            reserved = {"page", "limit", "search", "ordering", "format", "api_key"}
            params: dict[str, object] = {}
            for k, v in (filters or {}).items():
                if k in reserved:
                    raise InvalidInput(f"filter '{k}' is reserved; use the dedicated argument")
                params[k] = _TANGO_UNSAFE.sub(" ", v).strip()  # keeps "|", Tango's OR syntax
            params.update(search=clean_text(search), ordering=ordering, page=page, limit=limit)
            data = await client.get_json(base + RESOURCES[resource], params)
            results = data.get("results", []) if isinstance(data, dict) else data
            extras = {k: data[k] for k in ("_coverage", "meta", "_ignored_params") if isinstance(data, dict) and k in data}
            return envelope(f"Tango:{resource}", results, total=data.get("count") if isinstance(data, dict) else None,
                            notes=[TERMS_NOTE],
                            has_next=bool(data.get("next")) if isinstance(data, dict) else None, **extras)

        @mcp.tool(annotations=READ_ONLY, description="Get one Tango record by its id (UUID, PIID, UEI or topic id).")
        async def tango_get(
            resource: Resource,
            record_id: Annotated[str, Field(min_length=3, max_length=100,
                                            pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-]*(?:\.[A-Za-z0-9_\-]+)*$")],
        ) -> dict:
            data = await client.get_json(f"{base}{RESOURCES[resource]}{record_id}/")
            return envelope(f"Tango:{resource}", [data])

        @mcp.tool(annotations=READ_ONLY, description=(
            "Per-state coverage of Tango's SLED solicitations dataset. Read before interpreting any state count."))
        async def tango_sled_coverage() -> dict:
            data = await client.get_json(f"{base}/api/sled/opportunities/coverage/")
            return envelope("Tango:sled_coverage", data.get("states", []), totals=data.get("totals"),
                            generated_at=data.get("generated_at"))
