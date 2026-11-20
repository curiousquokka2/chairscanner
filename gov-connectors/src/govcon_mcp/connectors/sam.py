"""SAM.gov public APIs - opportunities, entities, exclusions, contract awards.

Requires a SAM.gov API key (``SAM_API_KEY``). Personal keys for non-federal
users with no SAM role are limited to **10 requests/day**; the shared cache
and conservative rate limit exist to protect that budget.

Docs:
  https://open.gsa.gov/api/get-opportunities-public-api/
  https://open.gsa.gov/api/entity-api/
  https://open.gsa.gov/api/exclusions-api/
  https://open.gsa.gov/api/contract-awards/
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Literal

from pydantic import Field

from ..errors import InvalidInput
from ..http import SafeClient
from ..validation import (Cage, IsoDate, Naics, Psc, StateCode, Uei, check_range, clean_text, envelope,
                          parse_iso, project, to_mmddyyyy)
from .base import READ_ONLY, Connector

BASE = "https://api.sam.gov"

NoticeType = Literal["u", "p", "a", "r", "s", "o", "g", "k", "i"]
_NOTICE_HELP = ("ptype: u=J&A, p=Presolicitation, a=Award, r=Sources Sought, s=Special Notice, "
                "o=Solicitation, g=Surplus Sale, k=Combined Synopsis/Solicitation, i=Intent to Bundle")

_OPP_FIELDS = ["noticeId", "title", "solicitationNumber", "fullParentPathName", "postedDate", "type", "baseType",
               "archiveDate", "setAside", "setAsideCode", "responseDeadLine", "naicsCode", "classificationCode",
               "active", "award", "pointOfContact", "placeOfPerformance", "officeAddress", "uiLink", "resourceLinks"]


def _sam_range(start: date, end: date) -> str:
    return f"[{to_mmddyyyy(start)},{to_mmddyyyy(end)}]"


class SAM(Connector):
    name = "sam"
    hosts = frozenset({"api.sam.gov"})
    requires = "sam_api_key"

    def build_client(self, transport=None) -> SafeClient:
        return SafeClient(self.name, self.hosts, secret_params={"api_key": self.settings.sam_api_key},
                          rate_per_s=1, burst=2, timeout_s=self.settings.http_timeout_s,
                          # Long cache: protects small daily quotas. Opportunities refresh daily upstream.
                          cache_ttl_s=max(self.settings.cache_ttl_s, 3600), transport=transport)

    def register(self, mcp) -> None:
        client = self.client

        @mcp.tool(annotations=READ_ONLY, description=(
            "Search SAM.gov contract opportunities (solicitations, sources sought, presolicitations, awards). "
            "posted_from/posted_to default to the last 30 days; max span 365 days. " + _NOTICE_HELP + ". "
            "Each call uses SAM.gov daily quota - prefer narrow filters."))
        async def sam_search_opportunities(
            posted_from: IsoDate | None = None,
            posted_to: IsoDate | None = None,
            title: Annotated[str | None, Field(max_length=200)] = None,
            solicitation_number: Annotated[str | None, Field(max_length=100)] = None,
            notice_id: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9\-]{8,64}$")] = None,
            ptype: NoticeType | None = None,
            naics: Naics | None = None,
            psc: Psc | None = None,
            set_aside: Annotated[str | None, Field(pattern=r"^[A-Z0-9]{2,10}$", description="Set-aside code, e.g. SBA, 8A, SDVOSBC, WOSB, HZC")] = None,
            state: StateCode | None = None,
            organization_name: Annotated[str | None, Field(max_length=200)] = None,
            response_deadline_from: IsoDate | None = None,
            response_deadline_to: IsoDate | None = None,
            limit: Annotated[int, Field(ge=1, le=100)] = 25,
            offset: Annotated[int, Field(ge=0, le=10000)] = 0,
        ) -> dict:
            end = parse_iso(posted_to, "posted_to") if posted_to else date.today()
            start = parse_iso(posted_from, "posted_from") if posted_from else end - timedelta(days=30)
            check_range(start, end, max_days=365, label="posted date range")
            params = {
                "postedFrom": to_mmddyyyy(start), "postedTo": to_mmddyyyy(end),
                "title": clean_text(title), "solnum": clean_text(solicitation_number), "noticeid": notice_id,
                "ptype": ptype, "ncode": naics, "ccode": psc, "typeOfSetAside": set_aside, "state": state,
                "organizationName": clean_text(organization_name), "limit": limit, "offset": offset,
            }
            if response_deadline_from or response_deadline_to:
                if not (response_deadline_from and response_deadline_to):
                    raise InvalidInput("provide both response_deadline_from and response_deadline_to")
                rs, re_ = parse_iso(response_deadline_from, "response_deadline_from"), parse_iso(response_deadline_to, "response_deadline_to")
                check_range(rs, re_, max_days=365, label="response deadline range")
                params.update(rdlfrom=to_mmddyyyy(rs), rdlto=to_mmddyyyy(re_))
            data = await client.get_json(f"{BASE}/opportunities/v2/search", params)
            rows = [project(r, _OPP_FIELDS) for r in data.get("opportunitiesData", [])]
            return envelope("SAM.gov Opportunities", rows, total=data.get("totalRecords"),
                            source_url="https://sam.gov/search/?index=opp",
                            notes=["Full notice description requires a separate authenticated call; open uiLink instead."])

        @mcp.tool(annotations=READ_ONLY, description=(
            "Look up SAM.gov entity registrations (public data only) by UEI, CAGE, legal name or free text. "
            "Returns registration status/expiry, addresses, business types and NAICS. "
            "Points of contact are deliberately omitted (data minimisation)."))
        async def sam_get_entity(
            uei: Uei | None = None,
            cage: Cage | None = None,
            legal_business_name: Annotated[str | None, Field(max_length=200)] = None,
            q: Annotated[str | None, Field(max_length=200, description="Free-text search")] = None,
            state: StateCode | None = None,
            primary_naics: Naics | None = None,
            registration_status: Annotated[Literal["A", "E"] | None, Field(description="A=Active, E=Expired")] = None,
            page: Annotated[int, Field(ge=0, le=999)] = 0,
        ) -> dict:
            if not any([uei, cage, legal_business_name, q, primary_naics]):
                raise InvalidInput("provide at least one of uei, cage, legal_business_name, q, primary_naics")
            params = {
                "ueiSAM": uei, "cageCode": cage, "legalBusinessName": clean_text(legal_business_name),
                "q": clean_text(q), "physicalAddressProvinceOrStateCode": state, "primaryNaics": primary_naics,
                "registrationStatus": registration_status, "page": page,
                "includeSections": "entityRegistration,coreData,assertions",
            }
            data = await client.get_json(f"{BASE}/entity-information/v3/entities", params)
            rows = []
            for e in data.get("entityData", []):
                core = e.get("coreData") or {}
                rows.append({
                    "entityRegistration": e.get("entityRegistration"),
                    "physicalAddress": core.get("physicalAddress"),
                    "entityInformation": core.get("entityInformation"),
                    "businessTypes": core.get("businessTypes"),
                    "goodsAndServices": (e.get("assertions") or {}).get("goodsAndServices"),
                })
            return envelope("SAM.gov Entity Management v3", rows, total=data.get("totalRecords"),
                            source_url="https://sam.gov/search/?index=ei")

        @mcp.tool(annotations=READ_ONLY, description=(
            "Search SAM.gov exclusions (debarments, suspensions, FASCSA orders) - a responsibility check "
            "before teaming or award."))
        async def sam_search_exclusions(
            uei: Uei | None = None,
            cage: Cage | None = None,
            exclusion_name: Annotated[str | None, Field(max_length=200)] = None,
            q: Annotated[str | None, Field(max_length=200)] = None,
            page: Annotated[int, Field(ge=0, le=999)] = 0,
        ) -> dict:
            if not any([uei, cage, exclusion_name, q]):
                raise InvalidInput("provide at least one of uei, cage, exclusion_name, q")
            params = {"ueiSAM": uei, "cageCode": cage, "exclusionName": clean_text(exclusion_name),
                      "q": clean_text(q), "page": page}
            data = await client.get_json(f"{BASE}/entity-information/v4/exclusions", params)
            rows = [project(r, ["exclusionDetails", "exclusionIdentification", "exclusionActions",
                                "exclusionAddress", "exclusionOtherInformation"])
                    for r in data.get("excludedEntity", [])]
            return envelope("SAM.gov Exclusions v4", rows, total=data.get("totalRecords"),
                            source_url="https://sam.gov/search/?index=ex")

        @mcp.tool(annotations=READ_ONLY, description=(
            "Search federal contract award records on the SAM.gov Contract Awards API (the FPDS successor). "
            "DoD awards signed in the last 90 days are not public. Dates are YYYY-MM-DD ranges."))
        async def sam_search_contract_awards(
            piid: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9\-]{4,50}$")] = None,
            referenced_idv_piid: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9\-]{4,50}$")] = None,
            awardee_uei: Uei | None = None,
            awardee_name: Annotated[str | None, Field(max_length=200)] = None,
            naics: Annotated[list[Naics] | None, Field(max_length=20)] = None,
            psc: Annotated[list[Psc] | None, Field(max_length=20)] = None,
            contracting_department_code: Annotated[str | None, Field(pattern=r"^[0-9A-Z]{4}$")] = None,
            set_aside_code: Annotated[str | None, Field(pattern=r"^[A-Z0-9]{2,10}$")] = None,
            pop_state: StateCode | None = None,
            fiscal_year: Annotated[int | None, Field(ge=2000, le=2100)] = None,
            date_signed_from: IsoDate | None = None,
            date_signed_to: IsoDate | None = None,
            piid_aggregation: bool = False,
            limit: Annotated[int, Field(ge=1, le=100)] = 25,
            offset: Annotated[int, Field(ge=0, le=4000)] = 0,
        ) -> dict:
            params = {
                "piid": piid, "referencedIdvPiid": referenced_idv_piid,
                "awardeeUniqueEntityId": awardee_uei,
                "awardeeLegalBusinessName": clean_text(awardee_name),
                "naicsCode": "~".join(naics) if naics else None,
                "productOrServiceCode": "~".join(psc) if psc else None,
                "contractingDepartmentCode": contracting_department_code, "typeOfSetAsideCode": set_aside_code,
                "placeOfPerformStateCode": pop_state, "fiscalYear": fiscal_year,
                "limit": limit, "offset": offset,
            }
            if piid_aggregation:
                if not piid:
                    raise InvalidInput("piid_aggregation requires piid")
                params["piidAggregation"] = "yes"
            if date_signed_from or date_signed_to:
                s = parse_iso(date_signed_from, "date_signed_from") if date_signed_from else date(2000, 1, 1)
                e = parse_iso(date_signed_to, "date_signed_to") if date_signed_to else date.today()
                check_range(s, e, label="date signed range")
                params["dateSigned"] = _sam_range(s, e)
            data = await client.get_json(f"{BASE}/contract-awards/v1/search", params)
            # The response's record list key is not pinned in the public docs; take the first list found.
            rows = next((v for v in data.values() if isinstance(v, list)), []) if isinstance(data, dict) else []
            extra = {k: v for k, v in data.items() if not isinstance(v, list)} if isinstance(data, dict) else {}
            return envelope("SAM.gov Contract Awards v1", rows[:limit], total=extra.get("totalRecords"),
                            meta=extra, source_url="https://sam.gov/search/?index=_all")
