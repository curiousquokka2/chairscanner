# Connection Log

Running record of every upstream connection this server opens, what it needs from a human, and its
verification status. **Update this file whenever a connector, host, key or status changes.**

Last updated: 2026-11-20

## 1. Summary

| Connector | Host(s) (egress allowlist) | Auth | Human action needed | Status |
|---|---|---|---|---|
| `usaspending` | `api.usaspending.gov` | None | None | Built; unit-tested; **live test pending** (sandbox network blocked) |
| `sam` | `api.sam.gov` | API key (`SAM_API_KEY`) | **Yes — create key (see §2.1)** | Built; unit-tested; disabled until key supplied |
| `calc` | `api.gsa.gov` | None | None | Built; unit-tested; live test pending |
| `sbir` | `api.www.sbir.gov` | None | None (but see outage note) | Built; unit-tested; **upstream API "under maintenance"** per sbir.gov/api |
| `tango` | `tango.makegov.com` (or `tango.dev`) | API key (`TANGO_API_KEY`, header `X-API-KEY`) | **Yes — create key (see §2.2)** | Built; unit-tested; disabled until key supplied |
| `sled` | `data.cityofnewyork.us`, `data.ny.gov`, `data.lacity.org`, `data.cityofchicago.org`, `data.austintexas.gov`, `data.texas.gov` | None (optional `SOCRATA_APP_TOKEN`) | Optional — app token for higher throttling limits | Built; unit-tested; all 6 datasets verified live 2026-11-20 via public fetch |

Ask the running server for live status at any time with the `govcon_connection_status` tool.

## 2. Human-in-the-loop actions

| # | What | Who | Steps | Where the value goes |
|---|---|---|---|---|
| 2.1 | **SAM.gov public API key** | Person with a SAM.gov account (Login.gov) | 1) Sign in at sam.gov → Profile → *Account Details*. 2) Under *Public API Key* click the eye icon, enter the one-time password emailed to you, copy the key. 3) For >10 calls/day, either get a SAM role (entity registration association) or request a **System Account** (Workspace → System Accounts; needs approval, IP allowlist, "read public" permission). Keys expire every 90 days — calendar a rotation. | `SAM_API_KEY` env var or `SAM_API_KEY_FILE` (secret mount). Never commit. |
| 2.2 | **Tango API key** | Person with a Tango/MakeGov account | Sign in at tango.makegov.com → account profile → *Create a new API key* → name it (e.g. "govcon-mcp-prod") → copy. Free tier covers every endpoint used here; some shape leaves need paid tiers. | `TANGO_API_KEY` or `TANGO_API_KEY_FILE` |
| 2.3 | Socrata app token (optional) | Anyone | Create a free account on any Socrata portal (e.g. data.cityofnewyork.us → Developer settings → *Create new app token*). One token works across Socrata portals. | `SOCRATA_APP_TOKEN` |
| 2.4 | OAuth issuer for remote deployment | IT / identity admin | Register this server as a protected resource in your IdP (Entra ID, Okta, Login.gov, Cognito…). Provide issuer URL, JWKS URL, the public MCP URL (used as `aud`), and a scope (e.g. `govcon.read`). | `GOVCON_OAUTH_ISSUER`, `GOVCON_OAUTH_JWKS_URL`, `GOVCON_PUBLIC_URL`, `GOVCON_OAUTH_SCOPES` |
| 2.5 | Network egress approval | Environment owner | The runtime must allow outbound HTTPS to exactly the hosts in §1 — nothing else is required. | Firewall / proxy allowlist |
| 2.6 | SBIR.gov data during outage | Program staff | If the API stays down, request bulk data from the SBIR helpdesk (address on sbir.gov/api) or use `tango_search(resource="sbir_topics")` for topics. | n/a |

## 3. Endpoint inventory

### USAspending (no key) — docs: https://api.usaspending.gov/docs/endpoints
| Tool | Method + path |
|---|---|
| `usaspending_search_awards` | `POST /api/v2/search/spending_by_award/` |
| `usaspending_get_award` | `GET /api/v2/awards/{generated_internal_id}/` |
| `usaspending_spending_by_category` | `POST /api/v2/search/spending_by_category/{category}/` |

### SAM.gov (key) — docs: https://open.gsa.gov/api/
| Tool | Path | Notes |
|---|---|---|
| `sam_search_opportunities` | `GET /opportunities/v2/search` | `postedFrom`/`postedTo` required, MM/dd/yyyy, ≤1 year span; `limit` ≤1000 (capped at 100 here) |
| `sam_get_entity` | `GET /entity-information/v3/entities` | Public data only; POCs dropped. v4 also exists — evaluate before migrating |
| `sam_search_exclusions` | `GET /entity-information/v4/exclusions` | 10 records/page upstream |
| `sam_search_contract_awards` | `GET /contract-awards/v1/search` | FPDS successor. DoD awards <90 days old are not public. Response list key not pinned in docs → connector takes the first list; **verify on first live call** |

Rate limits (official, per key/day): non-federal no role **10**; non-federal with role 1,000; federal personal 1,000; non-federal system 1,000; federal system 10,000. The connector caches SAM responses ≥1 h and throttles to 1 req/s.

Characters `& | { } ^ \` are rejected by SAM.gov in parameter values; the connector strips them.

### GSA CALC+ (no key) — docs: https://open.gsa.gov/api/dx-calc-api/
| Tool | Path |
|---|---|
| `calc_search_labor_rates` | `GET /acquisition/calc/v3/api/ceilingrates/` with `keyword`, `search=field:value`, `filter=...` |
| `calc_suggest` | same path with `suggest-contains=field:prefix` |

The legacy v2 `/rates/` API was retired Feb 2025; do not use it.

### SBIR.gov (no key) — docs: https://www.sbir.gov/api
| Tool | Path | Notes |
|---|---|---|
| `sbir_search_awards` | `GET /public/api/awards` | `agency`, `firm`, `year` (with agency), `ri`, `rows` (≤100 here), `start`. Solicitation/firm endpoints are no longer listed on the docs page, so they are not implemented. Agency code for DoD is now listed as `DOW`. |

### Tango (key) — docs: https://docs.makegov.com/api-reference/
| Tool | Path(s) |
|---|---|
| `tango_search` | allowlisted: `/api/{contracts,idvs,vehicles,subawards,otas,opportunities,forecasts,grants,entities,exclusions,protests}/`, `/api/sbir/{topics,solicitations}/`, `/api/sled/{opportunities,forecasts}/` |
| `tango_get` | `{resource path}{id}/` |
| `tango_sled_coverage` | `/api/sled/opportunities/coverage/` |

### SLED Socrata (no key) — docs: https://dev.socrata.com/docs/endpoints
See `sled_list_datasets` and [SLED_RESEARCH.md](SLED_RESEARCH.md). Each dataset was verified on 2026-11-20 by fetching `/resource/<id>.json?$limit=1` and `/api/views/<id>.json`.

## 4. Change log

| Date | Change |
|---|---|
| 2026-11-20 | Initial build: 6 connectors, 16 tools. Sandbox egress to all API hosts was blocked, so live tests are pending; unit tests (36) pass against mocked HTTP. SAM and Tango await keys. SBIR.gov API reported under maintenance. |
