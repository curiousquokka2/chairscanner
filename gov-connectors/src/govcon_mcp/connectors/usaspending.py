"""USAspending.gov API v2 - federal award spending. No key required.

Docs: https://api.usaspending.gov/docs/endpoints
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from ..errors import InvalidInput
from ..safehttp import SafeClient
from ..validation import (IsoDate, Naics, Psc, StateCode, check_range, clean_text, envelope, parse_iso)
from .base import READ_ONLY, Connector

BASE = "https://api.usaspending.gov/api/v2"

AWARD_TYPE_CODES = {
    "contracts": ["A", "B", "C", "D"],
    "idvs": ["IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B", "IDV_B_C", "IDV_C", "IDV_D", "IDV_E"],
    "grants": ["02", "03", "04", "05"],
    "loans": ["07", "08"],
    "direct_payments": ["06", "10"],
    "other_assistance": ["09", "11", "-1"],
}

# Field names differ between contract-like and assistance award groups.
_CONTRACT_FIELDS = ["Award ID", "Recipient Name", "Recipient UEI", "Award Amount", "Description",
                    "Start Date", "End Date", "Awarding Agency", "Awarding Sub Agency",
                    "Contract Award Type", "NAICS", "PSC", "generated_internal_id"]
_ASSISTANCE_FIELDS = ["Award ID", "Recipient Name", "Recipient UEI", "Award Amount", "Description",
                      "Start Date", "End Date", "Awarding Agency", "Awarding Sub Agency",
                      "Award Type", "CFDA Number", "generated_internal_id"]

AwardGroup = Literal["contracts", "idvs", "grants", "loans", "direct_payments", "other_assistance"]
Category = Literal["awarding_agency", "awarding_subagency", "recipient", "naics", "psc", "cfda",
                   "state_territory", "county", "district"]


def _filters(*, award_group: str, start_date: str, end_date: str, keywords: list[str] | None,
             naics: list[str] | None, psc: list[str] | None, recipient: str | None,
             awarding_agency: str | None, pop_state: str | None, set_aside: list[str] | None = None) -> dict:
    start, end = parse_iso(start_date, "start_date"), parse_iso(end_date, "end_date")
    check_range(start, end)
    # Search covers FY2008+ only (earliest 2007-10-01) per api_contracts/search_filters.md.
    if end.isoformat() < "2007-10-01":
        raise InvalidInput("USAspending search covers 2007-10-01 onward; use its bulk download for earlier data")
    if start.isoformat() < "2007-10-01":
        start_date = "2007-10-01"
    f: dict = {
        "time_period": [{"start_date": start_date, "end_date": end_date}],
        "award_type_codes": AWARD_TYPE_CODES[award_group],
    }
    if keywords:
        kws = [k for k in (clean_text(x, max_len=100) for x in keywords) if k and len(k) >= 3]
        if kws:
            f["keywords"] = kws
    if naics:
        f["naics_codes"] = {"require": naics}
    if psc:
        # Plain list form per api_contracts/search_filters.md (the require/exclude form takes tree paths
        # starting at Tier1 names such as "Service", not bare codes).
        f["psc_codes"] = psc
    if recipient:
        f["recipient_search_text"] = [clean_text(recipient)]
    if awarding_agency:
        f["agencies"] = [{"type": "awarding", "tier": "toptier", "name": clean_text(awarding_agency)}]
    if pop_state:
        f["place_of_performance_locations"] = [{"country": "USA", "state": pop_state}]
    if set_aside:
        f["set_aside_type_codes"] = set_aside
    return f


class USAspending(Connector):
    name = "usaspending"
    hosts = frozenset({"api.usaspending.gov"})

    def build_client(self, transport=None) -> SafeClient:
        return SafeClient(self.name, self.hosts, rate_per_s=4, burst=4, timeout_s=self.settings.http_timeout_s,
                          cache_ttl_s=self.settings.cache_ttl_s, transport=transport)

    def register(self, mcp) -> None:
        client = self.client

        @mcp.tool(annotations=READ_ONLY, description=(
            "Search federal awards on USAspending.gov (prime contracts, IDVs, grants, etc.). "
            "Use for past-performance research, incumbent and competitor analysis, and agency spend. "
            "Returns award IDs; pass generated_internal_id to usaspending_get_award for detail."))
        async def usaspending_search_awards(
            start_date: IsoDate,
            end_date: IsoDate,
            award_group: AwardGroup = "contracts",
            keywords: Annotated[list[str] | None, Field(max_length=10)] = None,
            naics: Annotated[list[Naics] | None, Field(max_length=20)] = None,
            psc: Annotated[list[Psc] | None, Field(max_length=20)] = None,
            recipient: Annotated[str | None, Field(max_length=200, description="Recipient name or UEI")] = None,
            awarding_agency: Annotated[str | None, Field(max_length=200, description="Top-tier agency name, e.g. 'Department of Defense'")] = None,
            pop_state: StateCode | None = None,
            limit: Annotated[int, Field(ge=1, le=100)] = 25,
            page: Annotated[int, Field(ge=1, le=100)] = 1,
        ) -> dict:
            fields = _ASSISTANCE_FIELDS if award_group in ("grants", "loans", "direct_payments", "other_assistance") else _CONTRACT_FIELDS
            body = {
                "filters": _filters(award_group=award_group, start_date=start_date, end_date=end_date, keywords=keywords,
                                    naics=naics, psc=psc, recipient=recipient, awarding_agency=awarding_agency,
                                    pop_state=pop_state),
                "fields": fields, "limit": limit, "page": page, "sort": "Award Amount", "order": "desc",
            }
            data = await client.post_json(f"{BASE}/search/spending_by_award/", body)
            results = data.get("results", [])
            for r in results:
                if r.get("generated_internal_id"):
                    r["usaspending_url"] = f"https://www.usaspending.gov/award/{r['generated_internal_id']}"
            return envelope("USAspending.gov", results, total=None,
                            has_next=(data.get("page_metadata") or {}).get("hasNext"),
                            source_url="https://www.usaspending.gov/search")

        @mcp.tool(annotations=READ_ONLY, description=(
            "Get full detail for one USAspending award by its generated_internal_id "
            "(e.g. CONT_AWD_..., CONT_IDV_..., ASST_NON_...)."))
        async def usaspending_get_award(
            generated_internal_id: Annotated[str, Field(max_length=220, pattern=r"^(CONT|ASST)_[A-Z]+_[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)*$")],
        ) -> dict:
            data = await client.get_json(f"{BASE}/awards/{generated_internal_id}/")
            keep = ["id", "generated_unique_award_id", "piid", "fain", "category", "type_description", "description",
                    "total_obligation", "base_and_all_options_value", "base_exercised_options",
                    "date_signed", "period_of_performance", "awarding_agency", "funding_agency", "recipient",
                    "place_of_performance", "latest_transaction_contract_data", "naics_hierarchy", "psc_hierarchy",
                    "parent_award", "subaward_count", "total_subaward_amount"]
            record = {k: data[k] for k in keep if k in data}
            return envelope("USAspending.gov", [record],
                            source_url=f"https://www.usaspending.gov/award/{generated_internal_id}")

        @mcp.tool(annotations=READ_ONLY, description=(
            "Aggregate federal obligations by a category (agency, sub-agency, recipient, NAICS, PSC, CFDA, "
            "state, county, district) for market sizing and top-competitor lists."))
        async def usaspending_spending_by_category(
            category: Category,
            start_date: IsoDate,
            end_date: IsoDate,
            award_group: AwardGroup = "contracts",
            keywords: Annotated[list[str] | None, Field(max_length=10)] = None,
            naics: Annotated[list[Naics] | None, Field(max_length=20)] = None,
            psc: Annotated[list[Psc] | None, Field(max_length=20)] = None,
            awarding_agency: Annotated[str | None, Field(max_length=200)] = None,
            pop_state: StateCode | None = None,
            limit: Annotated[int, Field(ge=1, le=100)] = 10,
        ) -> dict:
            body = {
                "filters": _filters(award_group=award_group, start_date=start_date, end_date=end_date, keywords=keywords,
                                    naics=naics, psc=psc, recipient=None, awarding_agency=awarding_agency,
                                    pop_state=pop_state),
                "limit": limit, "page": 1,
            }
            data = await client.post_json(f"{BASE}/search/spending_by_category/{category}/", body)
            return envelope("USAspending.gov", data.get("results", []),
                            has_next=(data.get("page_metadata") or {}).get("hasNext"),
                            notes=["'amount' is obligated dollars within the date range."])
