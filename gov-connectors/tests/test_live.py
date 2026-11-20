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


@pytest.fixture(scope="module")
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
    if err and ("HTTP 5" in str(out) or "network error" in str(out)):
        pytest.xfail("SBIR.gov API is in maintenance (documented on sbir.gov/api)")
    assert not err, out


async def test_sled_live(server):
    err, out = await call(server, "sled_query", {"dataset": "la_ramp_open_bids", "limit": 3})
    assert not err, out


@pytest.mark.skipif(not os.environ.get("SAM_API_KEY"), reason="SAM_API_KEY not set")
async def test_sam_live(server):
    err, out = await call(server, "sam_search_opportunities", {"ptype": "o", "naics": "541512", "limit": 3})
    assert not err, out


@pytest.mark.skipif(not os.environ.get("TANGO_API_KEY"), reason="TANGO_API_KEY not set")
async def test_tango_live(server):
    err, out = await call(server, "tango_sled_coverage")
    assert not err, out
