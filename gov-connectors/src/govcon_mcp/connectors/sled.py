"""SLED (state, local, education) procurement via official Socrata (SODA) open-data portals.

Most state/local e-procurement portals (Texas ESBD, Cal eProcure, Bonfire,
Jaggaer, Periscope...) publish no public API. Many governments do publish
procurement datasets on Socrata. This connector exposes an allowlisted
registry of datasets that were verified live, and builds SoQL from typed
filters - the model never sends raw SoQL (no query injection, no access to
arbitrary datasets on the host).

An app token (``SOCRATA_APP_TOKEN``) is optional; it raises throttling limits.
SODA docs: https://dev.socrata.com/docs/endpoints
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field

from ..errors import InvalidInput
from ..safehttp import SafeClient
from ..validation import IsoDate, envelope, parse_iso, project
from .base import READ_ONLY, Connector


@dataclass(frozen=True)
class Dataset:
    host: str
    dataset_id: str
    title: str
    publisher: str
    kind: str  # "solicitations", "awards", "purchase_orders", "notices"
    date_field: str | None
    amount_field: str | None
    text_fields: tuple[str, ...]  # fields searched by `keyword` (SoQL full text $q searches all)
    # Output allowlist (data minimisation: no personal contact fields). Applied after fetch rather than
    # via $select so a renamed upstream column degrades to a missing field instead of a 400.
    fields: tuple[str, ...]
    filterable: tuple[str, ...] = ()  # equality filters allowed


# Verified 2026-11-20 by fetching /resource/<id>.json and /api/views/<id>.json.
REGISTRY: dict[str, Dataset] = {
    "nyc_city_record": Dataset(
        "data.cityofnewyork.us", "qyyg-4tf5", "City Record Online (procurement notices)", "New York City (DCAS)",
        "notices", "start_date", "contract_amount", ("short_title", "additional_description_1"),
        ("request_id", "start_date", "end_date", "agency_name", "type_of_notice_description", "category_description",
         "short_title", "selection_method_description", "section_name", "pin", "contract_amount",
         "additional_description_1"),
        ("agency_name", "type_of_notice_description", "category_description", "section_name")),
    "ny_state_authorities_procurement": Dataset(
        "data.ny.gov", "ehig-g5x3", "Procurement Report for Local and State Authorities", "New York State ABO",
        "awards", "award_date", "contract_amount", ("procurement_description", "vendor_name"),
        ("authority_name", "fiscal_year_end_date", "vendor_name", "vendor_city", "vendor_state",
         "procurement_description", "type_of_procurement", "award_process", "award_date", "begin_date",
         "contract_amount", "amount_expended_to_date", "number_of_bids_or_proposals_received", "vendor_is_a_mwbe",
         "status"),
        ("authority_name", "type_of_procurement", "award_process", "status", "vendor_state")),
    "la_ramp_open_bids": Dataset(
        "data.lacity.org", "hf3r-utnq", "RAMP Open Bid Opportunities", "City of Los Angeles",
        "solicitations", "bidpost", None, ("title",),
        ("rampid", "title", "stagename", "category", "type", "bidpost", "closedate", "department", "url"),
        ("stagename", "type", "department", "category")),
    "chicago_contracts": Dataset(
        "data.cityofchicago.org", "rsxa-ify5", "Contracts (since 1993)", "City of Chicago",
        "awards", "approval_date", "award_amount", ("purchase_order_description", "vendor_name"),
        ("purchase_order_description", "purchase_order_contract_number", "revision_number", "specification_number",
         "contract_type", "start_date", "end_date", "approval_date", "department", "vendor_name", "vendor_id",
         "city", "state", "award_amount"),
        ("department", "contract_type", "vendor_name")),
    "austin_po_commodity_lines": Dataset(
        "data.austintexas.gov", "3ebq-e9iz", "Purchase Order commodity line detail (goods)", "City of Austin, TX",
        "purchase_orders", "award_date", "itm_tot_am", ("contract_name", "commodity_description", "lgl_nm"),
        ("commodity", "commodity_description", "extended_description", "quantity", "unit_price", "itm_tot_am",
         "master_agreement", "contract_name", "purchase_order", "award_date", "vendor_code", "lgl_nm", "city", "st"),
        ("commodity", "master_agreement", "lgl_nm")),
    "texas_tceq_contracts": Dataset(
        "data.texas.gov", "svjm-sdfz", "TCEQ Current Contracts & Purchase Orders",
        "Texas Commission on Environmental Quality", "awards", "start_date", "total_amount",
        ("project_name", "vendor_name_description"),
        ("po_contract_number", "vendor_name_description", "project_name", "start_date", "end_date", "total_amount",
         "pcc_code", "contract_or_po_2"),
        ("pcc_code", "contract_or_po_2")),
}

DatasetKey = Literal[tuple(REGISTRY)]  # type: ignore[valid-type]
_SAFE_VALUE = re.compile(r"^[\w .,&'()/#:\-]{1,120}$")


def _soql_literal(value: str) -> str:
    if not _SAFE_VALUE.match(value):
        raise InvalidInput("filter values may contain only letters, digits, spaces and . , & ' ( ) / # : -")
    return "'" + value.replace("'", "''") + "'"


class SLED(Connector):
    name = "sled"
    hosts = frozenset(d.host for d in REGISTRY.values())

    def build_client(self, transport=None) -> SafeClient:
        token = self.settings.socrata_app_token
        return SafeClient(self.name, self.hosts, secret_headers={"X-App-Token": token} if token else None,
                          rate_per_s=2, burst=4, timeout_s=self.settings.http_timeout_s,
                          cache_ttl_s=self.settings.cache_ttl_s, transport=transport)

    def register(self, mcp) -> None:
        client = self.client

        @mcp.tool(annotations=READ_ONLY, description=(
            "List the verified state/local government procurement datasets this server can query "
            "(official .gov Socrata open-data portals), with their filterable fields."))
        async def sled_list_datasets() -> dict:
            rows = [{"dataset": k, "title": d.title, "publisher": d.publisher, "kind": d.kind,
                     "date_field": d.date_field, "amount_field": d.amount_field,
                     "filterable_fields": list(d.filterable),
                     "portal_url": f"https://{d.host}/d/{d.dataset_id}"} for k, d in REGISTRY.items()]
            return envelope("SLED registry", rows, notes=[
                "Coverage is a handful of jurisdictions; absence of results is not absence of a market.",
                "For multi-state SLED solicitations use tango_search(resource='sled_opportunities')."])

        @mcp.tool(annotations=READ_ONLY, description=(
            "Query one registered state/local procurement dataset (see sled_list_datasets). "
            "keyword runs Socrata full-text search; equals applies exact-match filters on allowlisted fields; "
            "date_from/date_to and min_amount use the dataset's date/amount field. Newest first."))
        async def sled_query(
            dataset: DatasetKey,
            keyword: Annotated[str | None, Field(min_length=2, max_length=100)] = None,
            equals: Annotated[dict[str, str] | None, Field(max_length=5)] = None,
            date_from: IsoDate | None = None,
            date_to: IsoDate | None = None,
            min_amount: Annotated[float | None, Field(ge=0)] = None,
            limit: Annotated[int, Field(ge=1, le=200)] = 25,
            offset: Annotated[int, Field(ge=0, le=50000)] = 0,
        ) -> dict:
            d = REGISTRY[dataset]
            where: list[str] = []
            for field, value in (equals or {}).items():
                if field not in d.filterable:
                    raise InvalidInput(f"'{field}' is not filterable on {dataset}; allowed: {list(d.filterable)}")
                where.append(f"{field} = {_soql_literal(value)}")
            if date_from or date_to:
                if not d.date_field:
                    raise InvalidInput(f"{dataset} has no date field")
                if date_from:
                    where.append(f"{d.date_field} >= '{parse_iso(date_from, 'date_from').isoformat()}T00:00:00'")
                if date_to:
                    where.append(f"{d.date_field} <= '{parse_iso(date_to, 'date_to').isoformat()}T23:59:59'")
            if min_amount is not None:
                if not d.amount_field:
                    raise InvalidInput(f"{dataset} has no amount field")
                # Some portals store amounts as text; cast so the comparison is numeric.
                where.append(f"{d.amount_field}::number >= {float(min_amount)}")
            params = {
                "$limit": limit, "$offset": offset,
                "$order": f"{d.date_field} DESC" if d.date_field else None,
                "$where": " AND ".join(where) if where else None,
                "$q": _soql_q(keyword) if keyword else None,
            }
            url = f"https://{d.host}/resource/{d.dataset_id}.json"
            data = await client.get_json(url, params)
            rows = [project(r, d.fields) for r in data] if isinstance(data, list) else []
            return envelope(f"{d.publisher}: {d.title}", rows, source_url=f"https://{d.host}/d/{d.dataset_id}",
                            next_offset=offset + limit if len(rows) == limit else None)


def _soql_q(keyword: str) -> str:
    # $q is passed as a separate URL param (not interpolated into SoQL); strip quotes/control chars anyway.
    return re.sub(r"[\"'\\\x00-\x1f]", " ", keyword).strip()[:100]
