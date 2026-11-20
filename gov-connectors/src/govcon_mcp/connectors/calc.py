"""GSA CALC+ Labor Ceiling Rates API (v3). No key required.

Docs: https://open.gsa.gov/api/dx-calc-api/
Ceiling rates are GSA MAS *ceiling* prices, not prices paid - say so in IGCEs.
"""

from __future__ import annotations

import statistics
from typing import Annotated, Literal

from pydantic import Field

from ..safehttp import SafeClient
from ..validation import clean_text, envelope
from .base import READ_ONLY, Connector

BASE = "https://api.gsa.gov/acquisition/calc/v3/api/ceilingrates/"

# Codes seen in docs: HS, BA; others (AA, MA, PHD ...) exist but the full list is not published.
Education = Annotated[str, Field(pattern=r"^[A-Z]{2,4}$")]
_FIELDS = ["labor_category", "vendor_name", "idv_piid", "schedule", "sin", "category", "subcategory",
           "current_price", "next_year_price", "second_year_price", "education_level", "min_years_experience",
           "business_size", "security_clearance", "worksite", "contract_start", "contract_end"]


class CALC(Connector):
    name = "calc"
    hosts = frozenset({"api.gsa.gov"})

    def build_client(self, transport=None) -> SafeClient:
        return SafeClient(self.name, self.hosts, rate_per_s=3, burst=3, timeout_s=self.settings.http_timeout_s,
                          cache_ttl_s=max(self.settings.cache_ttl_s, 3600),  # data refreshes nightly
                          transport=transport)

    def register(self, mcp) -> None:
        client = self.client

        @mcp.tool(annotations=READ_ONLY, description=(
            "Search GSA CALC+ labor ceiling rates (GSA MAS hourly ceiling prices) for price analysis and IGCEs. "
            "Use keyword for partial matches across labor category/vendor/contract number, or exact_labor_category "
            "for an exact category. Returns rates plus min/median/mean/max for the returned page."))
        async def calc_search_labor_rates(
            keyword: Annotated[str | None, Field(min_length=2, max_length=100)] = None,
            exact_labor_category: Annotated[str | None, Field(max_length=200)] = None,
            vendor_name: Annotated[str | None, Field(max_length=200)] = None,
            contract_number: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9\-]{4,30}$")] = None,
            education_levels: Annotated[list[Education] | None, Field(max_length=6)] = None,
            min_experience_years: Annotated[int | None, Field(ge=0, le=45)] = None,
            max_experience_years: Annotated[int | None, Field(ge=0, le=45)] = None,
            min_price: Annotated[float | None, Field(ge=0, le=2000)] = None,
            max_price: Annotated[float | None, Field(ge=0, le=2000)] = None,
            business_size: Literal["S", "O"] | None = None,
            security_clearance: Literal["Yes", "No"] | None = None,
            worksite: Literal["Contractor", "Customer", "Both"] | None = None,
            sin: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9]{2,15}$")] = None,
            ordering: Literal["current_price", "labor_category", "education_level", "min_years_experience",
                              "vendor_name", "schedule"] = "current_price",
            sort: Literal["asc", "desc"] = "asc",
            page: Annotated[int, Field(ge=1, le=500)] = 1,
            page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        ) -> dict:
            params: list[tuple[str, object]] = [("page", page), ("page_size", page_size),
                                                ("ordering", ordering), ("sort", sort)]
            if keyword:
                params.append(("keyword", clean_text(keyword, max_len=100)))
            # Exact-match searches use field:value syntax.
            for field, value in (("labor_category", exact_labor_category), ("vendor_name", vendor_name),
                                 ("idv_piid", contract_number)):
                if value:
                    params.append(("search", f"{field}:{clean_text(value)}"))
            if education_levels:
                params.append(("filter", "education_level:" + "|".join(education_levels)))
            if min_experience_years is not None or max_experience_years is not None:
                params.append(("filter", f"experience_range:{min_experience_years or 0},{max_experience_years if max_experience_years is not None else 45}"))
            if min_price is not None or max_price is not None:
                params.append(("filter", f"price_range:{min_price or 0},{max_price if max_price is not None else 2000}"))
            for field, value in (("business_size", business_size), ("security_clearance", security_clearance),
                                 ("worksite", worksite), ("sin", sin)):
                if value:
                    params.append(("filter", f"{field}:{value}"))

            data = await client.get_json(BASE, params)
            hits = (data.get("hits") or {})
            rows = [{k: h["_source"].get(k) for k in _FIELDS if k in h.get("_source", {})}
                    for h in hits.get("hits", []) if isinstance(h, dict)]
            prices = [r["current_price"] for r in rows if isinstance(r.get("current_price"), (int, float))]
            stats = None
            if prices:
                stats = {"n": len(prices), "min": min(prices), "median": statistics.median(prices),
                         "mean": round(statistics.fmean(prices), 2), "max": max(prices),
                         "scope": "returned page only - widen page_size or paginate for full distribution"}
            total = hits.get("total")
            return envelope("GSA CALC+ Ceiling Rates", rows,
                            total=total.get("value") if isinstance(total, dict) else total,
                            page_price_stats=stats, source_url="https://buy.gsa.gov/pricing/",
                            notes=["Rates are GSA MAS ceiling prices (fully burdened), not prices paid."])

        @mcp.tool(annotations=READ_ONLY, description=(
            "Autocomplete real values from CALC+ (labor categories, vendor names or contract numbers) "
            "to feed exact searches in calc_search_labor_rates."))
        async def calc_suggest(
            field: Literal["labor_category", "vendor_name", "idv_piid"],
            contains: Annotated[str, Field(min_length=2, max_length=60)],
        ) -> dict:
            data = await client.get_json(BASE, [("suggest-contains", f"{field}:{clean_text(contains, max_len=60)}")])
            return envelope("GSA CALC+ Ceiling Rates", [data] if not isinstance(data, list) else data)
