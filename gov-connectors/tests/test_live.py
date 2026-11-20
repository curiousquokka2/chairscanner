"""Live smoke tests against the real APIs. Opt in with:  pytest -m live

Keyless sources always run; SAM/Tango run only when their keys are set.
Each test makes at most one upstream call (SAM personal keys may allow 10/day).
"""

import os

import pytest

from govcon_mcp.config import Settings
from govcon_mcp.server import build_server

from .conftest import call

pytestmark = [pytest.mark.live, pytest.mark.anyio]


@pytest.fixture  # function scope: each anyio test has its own event loop
def server():
    return build_server(Settings.from_env())


async def test_usaspending_live(server):
    err, out = await call(server, "usaspending_search_awards",
                          {"start_date": "2025-10-01", "end_date": "2026-09-30", "naics": ["541512"], "limit": 3})
    assert not err, out
    assert out["returned"] >= 1


async def test_calc_live(server):
    err, out = await call(server, "calc_search_labor_rates", {"keyword": "software", "page_size": 5})
    assert not err, out
    assert out["returned"] >= 1


async def test_sbir_live(server):
    err, out = await call(server, "sbir_search_awards", {"agency": "NSF", "rows": 3})
    if err and ("HTTP 5" in str(out) or "HTTP 403" in str(out) or "network error" in str(out)):
        pytest.xfail("SBIR.gov API is in maintenance (documented on sbir.gov/api)")
    assert not err, out


@pytest.mark.parametrize("dataset", ["nyc_city_record", "ny_state_authorities_procurement", "la_ramp_open_bids",
                                     "chicago_contracts", "austin_po_commodity_lines", "texas_tceq_contracts"])
async def test_sled_live(server, dataset):
    err, out = await call(server, "sled_query", {"dataset": dataset, "limit": 2, "date_from": "2020-01-01"})
    assert not err, out
    assert out["returned"] >= 1, f"{dataset}: no rows - check date_field/order against the live schema"


async def test_sled_live_filters(server):
    err, out = await call(server, "sled_query", {"dataset": "chicago_contracts", "keyword": "snow",
                                                 "min_amount": 10000, "limit": 2})
    assert not err, out


async def test_usaspending_category_and_detail_live(server):
    err, out = await call(server, "usaspending_spending_by_category",
                          {"category": "recipient", "start_date": "2025-10-01", "end_date": "2026-09-30",
                           "naics": ["541512"], "limit": 3})
    assert not err and out["returned"] >= 1, out
    err, out = await call(server, "usaspending_search_awards",
                          {"start_date": "2025-10-01", "end_date": "2026-09-30", "psc": ["D399"], "limit": 1,
                           "pop_state": "VA", "keywords": ["cloud"]})
    assert not err and out["returned"] >= 1, out
    gid = out["results"][0]["generated_internal_id"]
    err, detail = await call(server, "usaspending_get_award", {"generated_internal_id": gid})
    assert not err and detail["results"][0].get("generated_unique_award_id"), detail


async def test_calc_suggest_and_filters_live(server):
    err, out = await call(server, "calc_suggest", {"field": "labor_category", "contains": "engineer"})
    assert not err, out
    err, out = await call(server, "calc_search_labor_rates",
                          {"keyword": "engineer", "education_levels": ["BA"], "min_price": 50, "max_price": 250,
                           "business_size": "S", "page_size": 10})
    assert not err and out["returned"] >= 1, out


@pytest.mark.skipif(not os.environ.get("SAM_API_KEY"), reason="SAM_API_KEY not set")
async def test_sam_live(server):
    err, out = await call(server, "sam_search_opportunities", {"ptype": "o", "naics": "541512", "limit": 3})
    assert not err, out


@pytest.mark.skipif(not os.environ.get("TANGO_API_KEY"), reason="TANGO_API_KEY not set")
async def test_tango_live(server):
    err, out = await call(server, "tango_sled_coverage")
    assert not err, out
