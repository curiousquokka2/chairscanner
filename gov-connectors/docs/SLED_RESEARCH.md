# SLED Portal Research (state, local, education)

Question: which official .gov state/local contracting portals offer API access, and how should the
agents reach SLED data? Findings as of 2026-11-20.

## Findings

1. **There is no national SLED feed.** Each jurisdiction runs its own portal. Most state e-procurement
   systems (e.g. Texas ESBD, California Cal eProcure, and SaaS platforms such as Bonfire, Jaggaer,
   Periscope/BidSync, OpenGov Procurement) offer **no public read API**. OpenGov's Procurement API exists
   but is agency-scoped: it needs an agency user account, so it is not usable for market research
   ([OpenGov developer portal](https://developer.opengov.com/catalog/pro-api)).
2. **Open-data portals are the practical official route.** Many governments publish procurement
   datasets on Socrata, which exposes a uniform JSON API (SODA). No key is required for light use; an app
   token raises throttling limits ([Socrata docs](https://dev.socrata.com/docs/endpoints)).
3. **Tango aggregates SLED solicitations across states** (`/api/sled/opportunities/`, beta). Coverage is
   partial and grows one jurisdiction at a time. Tango warns that a thin per-state result may mean an
   unread portal rather than a quiet market. Its SLED rows carry no UEI, PIID or NAICS/PSC crosswalk
   ([Tango SLED docs](https://docs.makegov.com/api-reference/sled/)).
4. Commercial SLED aggregators (HigherGov, GovSpend, Deltek GovWin, BidNet, GovTribe) cover more, but
   they are paid and not official sources. GovTribe is already available as a separate connector in
   this workspace; it was not duplicated here.

## Recommended architecture

* **Breadth:** `tango_search(resource="sled_opportunities")` for open solicitations nationally. Check
  `tango_sled_coverage` first.
* **Depth/authority:** `sled_query` against verified official datasets (below). Add a dataset by
  appending to `REGISTRY` in `connectors/sled.py` after verifying it live. List its filterable fields,
  and add its host to the egress allowlist and to CONNECTIONS.md.

## Verified datasets (in the registry)

| Key | Publisher | Dataset | Kind |
|---|---|---|---|
| `nyc_city_record` | NYC DCAS | City Record Online `qyyg-4tf5` | Solicitations, awards, intents to award |
| `ny_state_authorities_procurement` | NYS Authorities Budget Office | `ehig-g5x3` | Awards |
| `la_ramp_open_bids` | City of Los Angeles | RAMP Open Bid Opportunities `hf3r-utnq` | Open solicitations (includes LAUSD and other regional buyers) |
| `chicago_contracts` | City of Chicago | Contracts `rsxa-ify5` | Awards since 1993 |
| `austin_po_commodity_lines` | City of Austin | `3ebq-e9iz` | PO line items (unit prices — useful for price analysis) |
| `texas_tceq_contracts` | Texas Commission on Environmental Quality | `svjm-sdfz` | Current contracts/POs |

Note: `dg92-zbpx` on NYC Open Data is labelled "City Record" by some third-party tools, but it holds
personnel-change notices. The procurement dataset is `qyyg-4tf5`.

## Candidates to evaluate next (not yet verified, so not in the registry)

* Socrata portals for more states and cities: Washington (data.wa.gov), Colorado
  (data.colorado.gov), Maryland (opendata.maryland.gov), Connecticut (data.ct.gov), Delaware
  (data.delaware.gov open bids), Montgomery County MD (data.montgomerycountymd.gov), Seattle, San
  Francisco (data.sfgov.org supplier contracts).
* State open-checkbook APIs (e.g. Checkbook NYC's XML API; Ohio Checkbook).
* CKAN-based state portals (some use `/api/3/action/datastore_search`). A CKAN adapter would follow
  the same registry pattern.
