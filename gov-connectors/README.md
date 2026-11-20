# govcon-mcp: Government Contracting Connectors

A read-only MCP server that gives Claude government-contracting agents typed, egress-controlled
access to:

| Source | Tools | Key? |
|---|---|---|
| USAspending.gov | `usaspending_search_awards`, `usaspending_get_award`, `usaspending_spending_by_category` | No |
| SAM.gov | `sam_search_opportunities`, `sam_get_entity`, `sam_search_exclusions`, `sam_search_contract_awards` | **Yes** |
| GSA CALC+ | `calc_search_labor_rates`, `calc_suggest` | No |
| SBIR.gov | `sbir_search_awards` | No |
| Tango (MakeGov) | `tango_search`, `tango_get`, `tango_sled_coverage` | **Yes** |
| SLED open data (Socrata) | `sled_list_datasets`, `sled_query` | No (optional token) |
| — | `govcon_connection_status` | — |

Connectors without their key are not registered, and `govcon_connection_status` explains what is
missing. See **[docs/CONNECTIONS.md](docs/CONNECTIONS.md)** for the live connection log and the
human-in-the-loop steps.

## Quick start (local, stdio)

```bash
cd gov-connectors
python -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements-lock.txt && pip install --no-deps -e .
pytest                      # unit tests (mocked HTTP, no network)
pytest -m live              # live smoke tests (needs egress; SAM/Tango tests need keys)
python scripts/mutation_check.py   # proves each security control has a failing test
export SAM_API_KEY_FILE=~/.secrets/sam_api_key   # or SAM_API_KEY=...
govcon-mcp                  # stdio
```

Claude Desktop / Claude Code config:
```json
{ "mcpServers": { "govcon": { "command": "govcon-mcp",
  "env": { "SAM_API_KEY_FILE": "/path/to/sam_key", "TANGO_API_KEY_FILE": "/path/to/tango_key" } } } }
```

## Remote (Claude custom connector)

```bash
GOVCON_OAUTH_ISSUER=https://idp.example.gov \
GOVCON_OAUTH_JWKS_URL=https://idp.example.gov/.well-known/jwks.json \
GOVCON_PUBLIC_URL=https://govcon.example.gov/mcp \
GOVCON_OAUTH_SCOPES=govcon.read \
GOVCON_ALLOWED_HOSTS=govcon.example.gov \
govcon-mcp --transport http --host 0.0.0.0 --port 8000
```
Put a TLS-terminating proxy in front, then add `https://govcon.example.gov/mcp` as a custom connector
in Claude. The server refuses a non-loopback bind without OAuth. See [docs/SECURITY.md](docs/SECURITY.md).

## Configuration

| Variable | Purpose |
|---|---|
| `SAM_API_KEY[_FILE]`, `TANGO_API_KEY[_FILE]`, `SOCRATA_APP_TOKEN[_FILE]` | Credentials (prefer `_FILE`) |
| `GOVCON_ENABLED` | Comma list to enable a subset, e.g. `usaspending,calc,sled` |
| `GOVCON_CACHE_TTL` / `GOVCON_HTTP_TIMEOUT` | Seconds (defaults 900 / 30) |
| `TANGO_BASE_URL` | `https://tango.makegov.com` (default) or `https://tango.dev` |
| `GOVCON_SAM_DAILY_BUDGET` / `GOVCON_TANGO_DAILY_BUDGET` | Local per-UTC-day cap on upstream calls (SAM default 10; `none` disables) |
| `GOVCON_OAUTH_SCOPES` | Required token scope(s); default `govcon.read` |
| `GOVCON_LOG_LEVEL` | Default `INFO`; logs go to stderr |

## Design

```
tool call ─► pydantic-validated params ─► connector (builds request, allowlisted fields)
          ─► SafeClient (host allowlist, secret injection, rate limit, cache, retry, size cap, no redirects)
          ─► upstream .gov API ─► projection/minimisation ─► envelope{source, results, untrusted_content}
```
* `src/govcon_mcp/safehttp.py`: the only code that touches the network.
* `src/govcon_mcp/connectors/*.py`: one file per source. Add a source by subclassing `Connector`.
* `docs/`: connection log, security model, SLED research.
