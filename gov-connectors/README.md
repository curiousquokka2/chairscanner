# govcon-mcp: Government Contracting Connectors

Six read-only MCP servers, **one per data source**, that give Claude government-contracting agents
typed, egress-controlled access to official data. Each server is a separate connector in Claude:
it registers only its own tools, loads only its own key, and talks only to its own hosts. All six
share one tested security core (`safehttp.py`, `validation.py`, `auth.py`).

| Connector (command) | Source | Tools | Key? | HTTP port | OAuth scope |
|---|---|---|---|---|---|
| `govcon-usaspending` | USAspending.gov | `usaspending_search_awards`, `usaspending_get_award`, `usaspending_spending_by_category` | No | 8001 | `govcon.usaspending.read` |
| `govcon-sam` | SAM.gov | `sam_search_opportunities`, `sam_get_entity`, `sam_search_exclusions`, `sam_search_contract_awards` | **Yes** | 8002 | `govcon.sam.read` |
| `govcon-calc` | GSA CALC+ | `calc_search_labor_rates`, `calc_suggest` | No | 8003 | `govcon.calc.read` |
| `govcon-sbir` | SBIR.gov | `sbir_search_awards` | No | 8004 | `govcon.sbir.read` |
| `govcon-tango` | Tango (MakeGov) | `tango_search`, `tango_get`, `tango_sled_coverage` | **Yes** | 8005 | `govcon.tango.read` |
| `govcon-sled` | State & local open data (6 Socrata portals) | `sled_list_datasets`, `sled_query` | Optional token | 8006 | `govcon.sled.read` |

Every server also has `govcon_connection_status`. A keyed server started without its key still
starts and exposes only that tool, which says what a human needs to supply. `govcon-mcp` runs all six
in one process for local convenience; prefer the separate servers. See
**[docs/CONNECTIONS.md](docs/CONNECTIONS.md)** for the live connection log and human-in-the-loop steps.

## Quick start (local, stdio)

```bash
cd gov-connectors
python -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements-lock.txt && pip install --no-deps -e .
pytest                      # unit + separation tests (mocked HTTP; spawns each server over stdio)
pytest -m live              # live smoke tests (needs egress; SAM/Tango tests need keys)
python scripts/mutation_check.py   # proves each security control has a failing test
```

Claude Desktop / Claude Code config: add only the connectors you want. Each server gets only its own key:
```json
{ "mcpServers": {
    "govcon-usaspending": { "command": "govcon-usaspending" },
    "govcon-calc":        { "command": "govcon-calc" },
    "govcon-sbir":        { "command": "govcon-sbir" },
    "govcon-sled":        { "command": "govcon-sled", "env": { "SOCRATA_APP_TOKEN_FILE": "/path/to/socrata_token" } },
    "govcon-sam":         { "command": "govcon-sam",  "env": { "SAM_API_KEY_FILE": "/path/to/sam_key" } },
    "govcon-tango":       { "command": "govcon-tango","env": { "TANGO_API_KEY_FILE": "/path/to/tango_key" } }
} }
```

## Remote (Claude custom connectors)

Run each server as its own process (ideally its own container) behind a TLS-terminating proxy, each
with its own public URL, which is also its OAuth audience. Example for SAM:
```bash
GOVCON_OAUTH_ISSUER=https://idp.example.gov \
GOVCON_OAUTH_JWKS_URL=https://idp.example.gov/.well-known/jwks.json \
GOVCON_PUBLIC_URL=https://sam.govcon.example.gov/mcp \
GOVCON_ALLOWED_HOSTS=sam.govcon.example.gov \
SAM_API_KEY_FILE=/run/secrets/sam_api_key \
govcon-sam --transport http --host 0.0.0.0        # port 8002, requires scope govcon.sam.read
```
Then add `https://sam.govcon.example.gov/mcp` as a custom connector in Claude, and repeat for each
source you want. A server refuses a non-loopback bind without OAuth. Separate audiences and scopes
mean a token for one connector is rejected by the others. See [docs/SECURITY.md](docs/SECURITY.md).

## Configuration

| Variable | Purpose |
|---|---|
| `SAM_API_KEY[_FILE]`, `TANGO_API_KEY[_FILE]`, `SOCRATA_APP_TOKEN[_FILE]` | Credentials (prefer `_FILE`) |
| `GOVCON_ENABLED` | All-in-one `govcon-mcp` only: comma list to enable a subset |
| `GOVCON_CACHE_TTL` / `GOVCON_HTTP_TIMEOUT` | Seconds (defaults 900 / 30) |
| `TANGO_BASE_URL` | `https://tango.makegov.com` (default) or `https://tango.dev` |
| `GOVCON_SAM_DAILY_BUDGET` / `GOVCON_TANGO_DAILY_BUDGET` | Local per-UTC-day cap on upstream calls (SAM default 10; `none` disables) |
| `GOVCON_OAUTH_SCOPES` | Required token scope(s); default `govcon.<source>.read` (all-in-one: `govcon.read`) |
| `GOVCON_LOG_LEVEL` | Default `INFO`; logs go to stderr |

## Design

```
tool call ─► pydantic-validated params ─► connector (builds request, allowlisted fields)
          ─► SafeClient (host allowlist, secret injection, rate limit, cache, retry, size cap, no redirects)
          ─► upstream .gov API ─► projection/minimisation ─► envelope{source, results, untrusted_content}
```
* `src/govcon_mcp/safehttp.py`: the only code that touches the network.
* `src/govcon_mcp/connectors/*.py`: one file per source. Add a source by subclassing `Connector`, adding it to
  `SOURCES` in `server.py` (title, summary, port) and to `SECRET_FOR` in `config.py` if it needs a key, then adding a console script in `pyproject.toml`.
* `docs/`: connection log, security model, SLED research, and [LOCAL_SETUP.md](docs/LOCAL_SETUP.md) (save the SAM key and run the live test on your own computer).
