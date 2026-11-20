"""SBIR.gov public awards API. No key required.

Docs: https://www.sbir.gov/api  (as of 2026-11 the page says the APIs are
"undergoing maintenance" - expect intermittent 5xx; the client retries then
reports a clear error. Tango's /api/sbir/topics/ is the fallback for topics.)
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from ..errors import InvalidInput
from ..safehttp import SafeClient
from ..validation import clean_text, envelope, project
from .base import READ_ONLY, Connector

BASE = "https://api.www.sbir.gov/public/api"

Agency = Literal["DOW", "DOD", "HHS", "NASA", "NSF", "DOE", "USDA", "EPA", "DOC", "ED", "DOT", "DHS"]

# Personal contact fields (poc/pi/ri phone & email) are dropped by default: data minimisation.
_FIELDS = ["firm", "award_title", "agency", "branch", "phase", "program", "agency_tracking_number", "contract",
           "proposal_award_date", "contract_end_date", "solicitation_number", "solicitation_year", "topic_code",
           "award_year", "award_amount", "uei", "hubzone_owned", "socially_economically_disadvantaged",
           "women_owned", "number_employees", "company_url", "city", "state", "zip", "ri_name",
           "research_area_keywords", "abstract", "award_link"]


class SBIR(Connector):
    name = "sbir"
    hosts = frozenset({"api.www.sbir.gov"})

    def build_client(self, transport=None) -> SafeClient:
        return SafeClient(self.name, self.hosts, rate_per_s=1, burst=2, timeout_s=self.settings.http_timeout_s,
                          cache_ttl_s=max(self.settings.cache_ttl_s, 3600), transport=transport)

    def register(self, mcp) -> None:
        client = self.client

        @mcp.tool(annotations=READ_ONLY, description=(
            "Search SBIR/STTR awards on SBIR.gov by agency, firm, award year and/or research institution. "
            "Use for small-business innovation past performance and competitor research. "
            "Sorted newest award first. Contact phone/email fields are omitted."))
        async def sbir_search_awards(
            agency: Agency | None = None,
            firm: Annotated[str | None, Field(min_length=2, max_length=200)] = None,
            year: Annotated[int | None, Field(ge=1983, le=2100)] = None,
            research_institution: Annotated[str | None, Field(min_length=2, max_length=200)] = None,
            rows: Annotated[int, Field(ge=1, le=100)] = 25,
            start: Annotated[int, Field(ge=0, le=100000)] = 0,
        ) -> dict:
            if not any([agency, firm, year, research_institution]):
                raise InvalidInput("provide at least one of agency, firm, year, research_institution")
            if year and not agency:
                raise InvalidInput("SBIR.gov year search requires agency as well")
            params = {"agency": agency, "firm": clean_text(firm), "year": year,
                      "ri": clean_text(research_institution), "rows": rows, "start": start}
            data = await client.get_json(f"{BASE}/awards", params)
            records = data if isinstance(data, list) else data.get("results", data.get("awards", []))
            rows_out = [project(r, _FIELDS, max_text=1200) for r in records if isinstance(r, dict)]
            return envelope("SBIR.gov Awards", rows_out, source_url="https://www.sbir.gov/awards",
                            next_start=start + rows if len(rows_out) == rows else None)
