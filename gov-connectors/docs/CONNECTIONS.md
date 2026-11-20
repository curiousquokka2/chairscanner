# Connection Log

Running record of every upstream connection this server opens, what it needs from a human, and its
verification status. **Update this file whenever a connector, host, key or status changes.**

Last updated: 2026-11-20 (live-verified; terms reviewed)

## 1. Summary

| Connector | Host(s) (egress allowlist) | Auth | Human action needed | Status |
|---|---|---|---|---|
| `usaspending` | `api.usaspending.gov` | None | None | **Live-verified 2026-11-20**: search, category, award detail |
| `sam` | `api.sam.gov` | API key (`SAM_API_KEY`, query param per docs) | **Yes — create key (see §2.1)** | Built; unit-tested; disabled until key supplied. **From this cloud sandbox api.sam.gov returns 404 on every path (2026-11-20)**: live test must run from another network |
| `calc` | `api.gsa.gov` | None | None | **Live-verified 2026-11-20**: search with filters, suggest |
| `sbir` | `api.www.sbir.gov` | None | None (but see §2.6) | **Down upstream**: its AWS API Gateway returns `403 Forbidden` on every call, including the docs' own example (2026-11-20). sbir.gov/api says "undergoing maintenance". The tool now returns this explanation and points to fallbacks. |
| `tango` | `tango.makegov.com` (or `tango.dev`) | API key (`TANGO_API_KEY`, header `X-API-KEY`) | **Yes — create key (see §2.2)** | Built; unit-tested; disabled until key supplied |
| `sled` | `data.cityofnewyork.us`, `data.ny.gov`, `data.lacity.org`, `data.cityofchicago.org`, `data.austintexas.gov`, `data.texas.gov` | None (optional `SOCRATA_APP_TOKEN`) | Optional — app token for higher throttling limits | **Live-verified 2026-11-20**: all 6 datasets queried through the connector, plus keyword/amount filters |

Ask the running server for live status at any time with the `govcon_connection_status` tool.

## 2. Human-in-the-loop actions

| # | What | Who | Steps | Where the value goes |
|---|---|---|---|---|
| 2.1 | **SAM.gov public API key** (read-public permission only) | Person with a SAM.gov account (Login.gov) | 1) Sign in at sam.gov → Profile → *Account Details*. 2) Under *Public API Key* click the eye icon, enter the one-time password emailed to you, copy the key. 3) For >10 calls/day, either get a SAM role (entity registration association) or request a **System Account** (Workspace → System Accounts; needs approval, IP allowlist, "read public" permission). Keys expire every 90 days — calendar a rotation. | `SAM_API_KEY` env var or `SAM_API_KEY_FILE` (secret mount). Never commit. |
| 2.2 | **Tango API key** (read the Tango terms concerns in §5 first) | Person with a Tango/MakeGov account | Sign in at tango.makegov.com → account profile → *Create a new API key* → name it (e.g. "govcon-mcp-prod") → copy. Free tier covers every endpoint used here; some shape leaves need paid tiers. | `TANGO_API_KEY` or `TANGO_API_KEY_FILE` |
| 2.3 | Socrata app token (**recommended**: Tyler's newer SODA3 API requires one for most queries, citing bot/AI-scraper load; SODA 2.1, used here, is still supported) | Anyone | Create a free account on any Socrata portal (e.g. data.cityofnewyork.us → Developer settings → *Create new app token*). One token works across Socrata portals. | `SOCRATA_APP_TOKEN` |
| 2.4 | OAuth issuer for remote deployment | IT / identity admin | Register this server as a protected resource in your IdP (Entra ID, Okta, Login.gov, Cognito…). Provide issuer URL, JWKS URL, the public MCP URL (used as `aud`), and a scope (e.g. `govcon.read`). | `GOVCON_OAUTH_ISSUER`, `GOVCON_OAUTH_JWKS_URL`, `GOVCON_PUBLIC_URL`, `GOVCON_OAUTH_SCOPES` |
| 2.5 | Network egress approval | Environment owner | The runtime must allow outbound HTTPS to exactly the hosts in §1 — nothing else is required. | Firewall / proxy allowlist |
| 2.6 | SBIR.gov data during outage | Program staff | If the API stays down, request bulk data from the SBIR helpdesk (address on sbir.gov/api) or use `tango_search(resource="sbir_topics")` for topics. | n/a |

### Accepted risks
| Date | Item | Decision |
|---|---|---|
| 2026-11-20 | The owner pasted a SAM.gov personal API key into the Claude chat. It was not written to any file, command or commit. | **Owner accepted the risk and chose not to rotate for now.** Impact if misused (read-public key): daily quota exhaustion, activity attributed to the owner's account. Revisit: rotate at the next scheduled key renewal or if any unexplained quota use or 429s appear. |

## 3. Endpoint inventory

### USAspending (no key) — docs: https://api.usaspending.gov/docs/endpoints
| Tool | Method + path |
|---|---|
| `usaspending_search_awards` | `POST /api/v2/search/spending_by_award/` |
| `usaspending_get_award` | `GET /api/v2/awards/{generated_internal_id}/` |
| `usaspending_spending_by_category` | `POST /api/v2/search/spending_by_category/{category}/` |

Filter contract read in full 2026-11-20:
https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/search_filters.md
- `psc_codes`: a plain list of codes. The `require`/`exclude` form takes tree paths starting at Tier 1
  names ("Service", "Product", "Research and Development"). The first build sent `[[code]]`, which
  the live API rejected with 422; fixed.
- `recipient_search_text`: at most 1 item (complies). Earliest date 2007-10-01 (FY2008); an end date
  before that is now rejected locally.

### SAM.gov (key) — docs: https://open.gsa.gov/api/
| Tool | Path | Notes |
|---|---|---|
| `sam_search_opportunities` | `GET /opportunities/v2/search` | `postedFrom`/`postedTo` required, MM/dd/yyyy, ≤1 year span; `limit` ≤1000 (capped at 100 here) |
| `sam_get_entity` | `GET /entity-information/v3/entities` | Public data only; POCs dropped. v4 also exists — evaluate before migrating |
| `sam_search_exclusions` | `GET /entity-information/v4/exclusions` | 10 records/page upstream |
| `sam_search_contract_awards` | `GET /contract-awards/v1/search` | FPDS successor. DoD awards <90 days old are not public. Response list key not pinned in docs → connector takes the first list; **verify on first live call** |

Rate limits (official, per key/day): non-federal no role **10**; non-federal with role 1,000; federal personal 1,000; non-federal system 1,000; federal system 10,000. The connector caches SAM responses ≥1 h, throttles to 1 req/s, and enforces a local budget (`GOVCON_SAM_DAILY_BUDGET`, default 10). **Raise it to match your key's tier.**

**Key permission:** use a key with *read public* only. FOUO/Sensitive system-account keys return CUI. See SECURITY.md → Credential reach.

Characters `& | { } ^ \` are rejected by SAM.gov in parameter values; the connector strips them.

**How the key is sent (docs read in full 2026-11-20).** For all four public endpoints used here, the
official docs and the Opportunities OpenAPI file document the key **only** as the `api_key` query parameter
(`in: query`, required). The `X-Api-Key` header is documented **only** for "Sensitive" POST calls from
federal system accounts with HTTP Basic auth, which this server must not use. Header delivery for public GET
calls is therefore **unverified**. Some third-party summaries claim it works; they are not authoritative.
Decision: keep the documented query parameter. Do **not** rely on a proxy that injects the key as a header.

**Reachability from the cloud sandbox: unverified.** On 2026-11-20 every `api.sam.gov` path, including the
bare root and the docs' own example URL, returned `404` with an empty body and `server: istio-envoy`.
That happened with no key, a fake header key and a fake query key alike. Other allowlisted hosts respond normally from the same sandbox.
Cause unknown: possibly SAM.gov refusing this network, or a gateway change. To confirm, run
`pytest -m live -k sam` with a real key from a US workstation; if it also 404s there, re-read the
SAM.gov change log / status page.

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

## 5. Terms of use (read 2026-11-20)

| Source | Terms | What they require | Concern / status |
|---|---|---|---|
| USAspending, SAM.gov, CALC+, SBIR.gov | Federal public data (US government works) | Use SAM keys within their permissions | SAM key must be read-public only (CUI risk) |
| Tango (**owner decision 2026-11-20: agents serve only the owner** → permitted under §3(a) as Customer Personnel; no Order Form needed) | https://tango.makegov.com/terms/ (v2.0.0, applies to every account from 2026-12-01) | §3(a): may build our own MCP server on the API; it may serve **only our Personnel and authenticated users of our own application**. §3(b): showing data to External Users needs a link back to source/Tango per record and **no bulk exports**. §3(c): replicating datasets (systematic paging), redistributing, reselling, or **rewrapping Tango's own MCP server** needs an Order Form. §4(c): no sharing keys outside the organisation. Cache ≤30 days. | **Needs your decision:** if the agents serve clients outside your organisation, check §3(b) and consider an Order Form. Code guardrails: page cap of 20 per query, terms note in every result, 15-min cache. |
| NYC Open Data | https://opendata.cityofnewyork.us/overview/#termsofuse (+ NYC.gov ToU) | No warranty; agency-specific terms may apply | None blocking |
| NY State (OPEN-NY) | https://data.ny.gov/download/77gx-ii52/application/pdf (modified 2013-03-08) | Lawful use only; no attribution required | None |
| Los Angeles | https://data.lacity.org/terms-of-use | No warranty; must not collect or store third parties' PII without City authorization | Contact fields are already dropped |
| Chicago | https://www.chicago.gov/city/en/narr/foia/data_disclaimer.html | Derived apps **must display a specific disclaimer**; indemnifies the City | Disclaimer now returned verbatim in every `chicago_contracts` result. The agent or UI must show it |
| Austin | https://data.austintexas.gov/stories/s/ranj-cccq (read in full 2026-11-20 via the portal's stories API) | Public domain, free and unrestricted. **Asks** for attribution to the City and the source department. **Forbids** re-identifying individuals or combining datasets to do so; any PII found must be destroyed and the City notified | Resolved: attribution line added to results. The PO dataset holds vendor (business) records, not individuals |
| Texas (data.texas.gov) | No portal-specific public terms (searched the portal catalog and footer, 2026-11-20). Footer links to the Tyler Technologies platform terms: https://www.tylertech.com/terms/socrata-terms-of-service | Tyler's general terms bar bots and scrapers and commercial redistribution of "the Services", but say service-specific terms take precedence. Tyler documents the SODA API for programmatic access (dev.socrata.com), with fair-use throttling. Tyler's customer contract makes each government responsible for public data-use terms | Resolved, low risk: official API, light use, attribution to TCEQ added. Get a free app token (§2.3) |
| gitleaks-action (CI) | https://github.com/gitleaks/gitleaks-action | Proprietary licence since v2; **free for personal-account repos**, organisations need a free `GITLEAKS_LICENSE` | OK for `curiousquokka2/chairscanner` (personal) |

## 4. Change log

| Date | Change |
|---|---|
| 2026-11-20 | Austin and Texas terms read in full and resolved (attribution added to results). Tango scope confirmed as owner-only. CI Actions pinned to commit SHAs (checkout v7.0.1, setup-python v7.1.0, gitleaks-action v3.0.0), resolved with `git ls-remote` and cross-checked against release notes. Found that the pre-existing `run_scanner.yml` still uses `checkout@v3` and `setup-python@v4`, which probably no longer run; left unchanged pending the owner's OK. 59 tests; 19/19 controls proven. |
| 2026-11-20 | Live verification and terms review: 11 live tests pass (USAspending, CALC+, 6 SLED datasets, filters). Fixed USAspending PSC filter format (live 422). Confirmed SBIR.gov down upstream (403). Terms read for all sources (§5): added Chicago's required disclaimer, Tango guardrails, and Austin/Texas marked unverified. Security: HTTP-client logs leaked request URLs (including SAM `api_key`) at INFO through any non-`main()` entry point; a redaction filter now covers every entry point. CI moved to Node 24 actions (checkout/setup-python v7, gitleaks-action v3), since the Node 20 versions stopped running on 2026-09-16. 58 tests; 18/18 controls proven by mutation. |
| 2026-11-20 | Hardening pass: daily quota budgets, mandatory OAuth scope, `/healthz`, tighter path-ID patterns, `http.py`→`safehttp.py`, hash-pinned lock (pip-audit clean), Dependabot, gitleaks + mutation check in CI. 51 tests; 14/14 controls proven by mutation. |
| 2026-11-20 | Initial build: 6 connectors, 16 tools. Sandbox egress to all API hosts was blocked, so live tests are pending; unit tests (36) pass against mocked HTTP. SAM and Tango await keys. SBIR.gov API reported under maintenance. |
