"""Request construction, validation and output minimisation per connector."""

import json

import pytest
from pydantic import SecretStr

from govcon_mcp.config import Settings

from .conftest import call

pytestmark = pytest.mark.anyio


# ---------------- USAspending ----------------
async def test_usaspending_search_builds_filters(make_server):
    server, rec = make_server({"spending_by_award": {"results": [{"Award ID": "X1", "generated_internal_id": "CONT_AWD_X1"}],
                                                     "page_metadata": {"hasNext": False}}})
    err, out = await call(server, "usaspending_search_awards", {
        "start_date": "2024-10-01", "end_date": "2025-09-30", "naics": ["541512"], "pop_state": "VA",
        "keywords": ["cloud migration"]})
    assert not err
    body = json.loads(rec.last.content)
    assert rec.last.url.host == "api.usaspending.gov"
    assert body["filters"]["award_type_codes"] == ["A", "B", "C", "D"]
    assert body["filters"]["naics_codes"] == {"require": ["541512"]}

    assert body["filters"]["place_of_performance_locations"] == [{"country": "USA", "state": "VA"}]
    assert out["results"][0]["usaspending_url"].endswith("CONT_AWD_X1")
    assert out["untrusted_content"] is True


async def test_usaspending_rejects_bad_dates_before_network(make_server):
    server, rec = make_server()
    err, _ = await call(server, "usaspending_search_awards", {"start_date": "2025-13-40", "end_date": "2025-01-01"})
    assert err and not rec.requests
    err, _ = await call(server, "usaspending_search_awards", {"start_date": "2025-06-01", "end_date": "2025-01-01"})
    assert err and not rec.requests


async def test_usaspending_award_id_pattern_blocks_path_traversal(make_server):
    server, rec = make_server()
    err, _ = await call(server, "usaspending_get_award", {"generated_internal_id": "../../references/x"})
    assert err and not rec.requests


# ---------------- SAM.gov ----------------
async def test_sam_opportunities_params_and_key(make_server):
    server, rec = make_server({"opportunities/v2/search": {"totalRecords": 1, "opportunitiesData": [
        {"noticeId": "abc", "title": "T", "links": [{"href": "https://api.sam.gov/x?api_key=SAMSECRET123"}]}]}})
    err, out = await call(server, "sam_search_opportunities", {
        "posted_from": "2026-10-01", "posted_to": "2026-11-01", "naics": "541512", "ptype": "o",
        "title": "cyber & {inject}"})
    assert not err
    p = rec.last.url.params
    assert p["postedFrom"] == "10/01/2026" and p["postedTo"] == "11/01/2026"
    assert p["ncode"] == "541512" and p["ptype"] == "o"
    assert p["api_key"] == "SAMSECRET123"
    assert not set("&{}") & set(p["title"])  # SAM forbidden chars stripped
    assert "SAMSECRET123" not in json.dumps(out)
    assert "links" not in out["results"][0]


async def test_sam_range_over_one_year_rejected(make_server):
    server, rec = make_server()
    err, out = await call(server, "sam_search_opportunities", {"posted_from": "2024-01-01", "posted_to": "2025-06-01"})
    assert err and "365" in str(out) and not rec.requests


async def test_sam_entity_omits_points_of_contact(make_server):
    server, rec = make_server({"entity-information/v3/entities": {"totalRecords": 1, "entityData": [{
        "entityRegistration": {"ueiSAM": "ABCDEFGHJKLM"}, "coreData": {"physicalAddress": {"city": "X"}},
        "pointsOfContact": {"governmentBusinessPOC": {"firstName": "Jane"}}}]}})
    err, out = await call(server, "sam_get_entity", {"uei": "ABCDEFGHJKLM"})
    assert not err
    assert "Jane" not in json.dumps(out)
    assert rec.last.url.params["ueiSAM"] == "ABCDEFGHJKLM"


async def test_sam_tools_absent_without_key(make_server):
    server, _ = make_server(settings=Settings(cache_ttl_s=0))
    names = {t.name for t in await server.list_tools()}
    assert "sam_search_opportunities" not in names and "tango_search" not in names
    assert "usaspending_search_awards" in names
    _, out = await call(server, "govcon_connection_status")
    sam = next(c for c in out["connectors"] if c["connector"] == "sam")
    assert not sam["enabled"] and "SAM_API_KEY" in sam["status"]


async def test_sam_contract_awards_ranges(make_server):
    server, rec = make_server({"contract-awards": {"totalRecords": 2, "awardSummary": [{"a": 1}, {"a": 2}]}})
    err, out = await call(server, "sam_search_contract_awards", {
        "naics": ["541511", "541512"], "date_signed_from": "2025-01-01", "date_signed_to": "2025-03-31"})
    assert not err and out["returned"] == 2
    assert rec.last.url.params["naicsCode"] == "541511~541512"
    assert rec.last.url.params["dateSigned"] == "[01/01/2025,03/31/2025]"


# ---------------- CALC+ ----------------
async def test_calc_filters_and_stats(make_server):
    hits = {"hits": {"total": {"value": 3}, "hits": [
        {"_source": {"labor_category": "Engineer II", "current_price": p}} for p in (100.0, 120.0, 200.0)]}}
    server, rec = make_server({"ceilingrates": hits})
    err, out = await call(server, "calc_search_labor_rates", {
        "keyword": "engineer", "education_levels": ["BA", "MA"], "min_price": 50, "max_price": 300})
    assert not err
    filters = rec.last.url.params.get_list("filter")
    assert "education_level:BA|MA" in filters and "price_range:50.0,300.0" in filters
    assert out["page_price_stats"]["median"] == 120.0 and out["total_available"] == 3


# ---------------- SBIR ----------------
async def test_sbir_strips_contact_pii(make_server):
    server, rec = make_server({"public/api/awards": [{"firm": "Acme", "poc_email": "a@b.c", "pi_phone": "555",
                                                      "award_amount": 150000}]})
    err, out = await call(server, "sbir_search_awards", {"agency": "NASA", "year": 2024})
    assert not err
    dumped = json.dumps(out)
    assert "a@b.c" not in dumped and "555" not in dumped and "Acme" in dumped
    assert rec.last.url.params["agency"] == "NASA"


# ---------------- Tango ----------------
async def test_tango_header_auth_and_reserved_filters(make_server):
    server, rec = make_server({"/api/sled/opportunities/": {"count": 1, "results": [{"title": "Roof"}], "next": None}})
    err, out = await call(server, "tango_search", {"resource": "sled_opportunities",
                                                   "filters": {"state": "TX", "status": "open|unknown"}})
    assert not err
    assert rec.last.headers["X-API-KEY"] == "TANGOSECRET456"
    assert "TANGOSECRET456" not in str(rec.last.url)
    assert rec.last.url.params["status"] == "open|unknown"
    # The route exists, so only the reserved-key control can make these fail.
    for reserved in ("api_key", "page", "format"):
        err, _ = await call(server, "tango_search", {"resource": "sled_opportunities", "filters": {reserved: "x"}})
        assert err, reserved


async def test_tango_base_url_must_be_allowlisted(make_server):
    server, _ = make_server(settings=Settings(tango_api_key=SecretStr("k"), tango_base_url="https://evil.example.com"))
    _, out = await call(server, "govcon_connection_status")
    tango = next(c for c in out["connectors"] if c["connector"] == "tango")
    assert not tango["enabled"] and "configuration error" in tango["status"]


# ---------------- SLED (Socrata) ----------------
async def test_sled_query_builds_safe_soql(make_server):
    server, rec = make_server({"rsxa-ify5": [{"vendor_name": "V", "award_amount": "10", "email": "x@y.z"}]})
    err, out = await call(server, "sled_query", {
        "dataset": "chicago_contracts", "keyword": "snow", "equals": {"department": "DEPT OF STREETS"},
        "date_from": "2025-01-01", "min_amount": 1000})
    assert not err
    where = rec.last.url.params["$where"]
    assert "department = 'DEPT OF STREETS'" in where and "approval_date >= '2025-01-01T00:00:00'" in where
    assert "award_amount::number >= 1000.0" in where
    assert "x@y.z" not in json.dumps(out)


@pytest.mark.parametrize("value", ["x' OR 1=1 --", "a;b", "x\" OR", "a\nb"])
async def test_sled_rejects_injection(make_server, value):
    server, rec = make_server()
    err, _ = await call(server, "sled_query", {"dataset": "chicago_contracts", "equals": {"department": value}})
    assert err and not rec.requests


async def test_sled_rejects_unlisted_field_and_dataset(make_server):
    server, rec = make_server()
    err, _ = await call(server, "sled_query", {"dataset": "chicago_contracts", "equals": {"vendor_id": "1"}})
    assert err
    err, _ = await call(server, "sled_query", {"dataset": "some_other_dataset"})
    assert err and not rec.requests



async def test_usaspending_psc_uses_documented_list_form(make_server):
    # api_contracts/search_filters.md: psc_codes is a plain list of codes (live API 422s on [[code]] paths).
    server, rec = make_server({"spending_by_award": {"results": [], "page_metadata": {}}})
    err, _ = await call(server, "usaspending_search_awards",
                        {"start_date": "2025-10-01", "end_date": "2026-09-30", "psc": ["D399", "R408"]})
    assert not err and json.loads(rec.last.content)["filters"]["psc_codes"] == ["D399", "R408"]
