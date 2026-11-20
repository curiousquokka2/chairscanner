# Security Model (zero trust)

Assume every boundary is hostile: the calling model (prompt injection), upstream APIs (compromise,
poisoned records), the network, and the deployment host.

| Threat | Control | Where |
|---|---|---|
| Model tricked into calling arbitrary URLs (SSRF / data exfiltration) | Every connector has its own exact-host HTTPS allowlist. Tools take typed parameters, never URLs or paths. Tango resources and SLED datasets are allowlisted enumerations. | `safehttp.py::_check_url`, `connectors/*` |
| API key leakage | Keys are read from env or `*_FILE` secret mounts into `SecretStr`. Each key goes only to its own connector's client, is injected at send time, is left out of cache keys, and is scrubbed from error text **and** response bodies. Keys go in headers where the upstream supports it (Tango, Socrata). SAM.gov requires a query param, so logs must never record SAM URLs. | `config.py`, `safehttp.py` |
| Redirect-based key exfiltration | `follow_redirects=False`; any 3xx is an error. | `safehttp.py` |
| Injection into upstream query languages | Pydantic patterns on IDs, dates and codes. SAM's forbidden characters are stripped. SoQL is built server-side from allowlisted fields, with a strict value regex and quote escaping. The model cannot send raw SoQL. | `validation.py`, `sled.py` |
| Prompt injection via returned records | Responses are wrapped in an envelope with `untrusted_content: true`. Server instructions tell the agent never to follow instructions found in data. Long text is truncated. | `validation.py::envelope`, `server.py` |
| Resource exhaustion / quota burn (OWASP LLM10) | Timeouts, an 8 MB response cap, JSON-only bodies, per-connector token-bucket rate limits, bounded retries honouring `Retry-After`, a TTL cache (≥1 h for SAM), and capped page sizes. A **local daily budget** hard-stops upstream calls (SAM default 10/UTC day; retries count, cache hits don't), so a looping agent or one noisy user on a shared deployment cannot burn the key's quota. | `safehttp.py::_DailyBudget`, `config.py` |
| PII over-collection | Output allowlists: SAM points of contact, SBIR phone/email, and city contact names/emails are dropped. | connectors |
| Unauthenticated remote access | HTTP transport binds loopback by default. A non-loopback bind **refuses to start** without OAuth. When enabled: JWT with asymmetric algorithms only (`alg=none`/HS256 rejected), JWKS over HTTPS, required `iss`/`aud`/`exp`/`sub`, and a **mandatory** scope (default `govcon.read`; an empty scope list refuses to start). Without a required scope, any token your IdP mints for this audience would be accepted. PyJWT's 30 s cooldown limits JWKS refetches triggered by unknown `kid`s. `/healthz` is unauthenticated (SDK design for custom routes) and returns only `{"status":"ok"}`. DNS-rebinding protection is on, with Host and Origin allowlists. Stateless HTTP (no server-side sessions). | `server.py`, `auth.py` |
| Secrets in logs | `safehttp.py` installs a log filter on the HTTP-client and app loggers that scrubs every registered secret at **any** level, and sets client loggers to WARNING. Found in live testing: the MCP SDK configures INFO logging, and httpx2 logs full URLs (SAM's key is a query param). The earlier `main()`-only fix missed other entry points. | `safehttp.py::_RedactSecrets` |
| Error-message leakage | Only `GovconError` (sanitised) messages reach the model; other exceptions become generic errors. Logs go to stderr and never include params. | `errors.py`, `server.py` |
| Write actions | None exist. Every tool is annotated `readOnlyHint=True`. | `connectors/base.py` |
| Supply chain | Few dependencies, major-version bounds in `pyproject.toml`. CI installs from `requirements-lock.txt` (36 packages, hash-pinned, `--require-hashes`). `pip-audit` runs in CI (clean on 2026-11-20). Dependabot covers pip and Actions, and gitleaks scans full history in CI. Actions moved to Node 24 majors (Node 20 actions stopped running on 2026-09-16). gitleaks-action is proprietary-licensed but free for personal-account repos. Actions pinned to full commit SHAs (2026-11-20); Dependabot proposes bumps. | `requirements-lock.txt`, `.github/` |
| Stdlib shadowing | The network module is `safehttp.py`, not `http.py`; the old name shadowed the stdlib `http` package whenever the package dir was on `sys.path`. | — |

## Credential reach (what each key unlocks beyond this server)

| Credential | Reaches | Rule |
|---|---|---|
| `SAM_API_KEY` | Every SAM.gov API at the account's sensitivity level. A **Federal System Account with "Read FOUO"/"Read Sensitive"** returns CUI (hierarchy, POC email/phone; Sensitive adds banking and TIN). Output projection is not a sufficient control for CUI. | Use a **personal or system key with "read public" only**. Never configure a FOUO/Sensitive key on this server. |
| `TANGO_API_KEY` | All Tango read endpoints at the account's tier (including eBuy requests under your own Schedule contracts, if linked). | Use a dedicated key named for this deployment; revoke on decommission. Prefer an account with no eBuy link. |
| `SOCRATA_APP_TOKEN` | Throttling identity only, no data access. | Low risk; still keep it out of the repo. |
| OAuth tokens (inbound) | This server only, if the IdP binds `aud` to `GOVCON_PUBLIC_URL`. | Issue a dedicated scope; never reuse one that other apps also accept. |

## Proving the controls
`python scripts/mutation_check.py` disables each of 19 security and terms controls in turn and requires the suite
to fail. 19/19 were killed on 2026-11-20 (the script refuses to run unless the unmutated suite is green, because a red baseline makes every mutant look killed) (CI runs it on every push). Authn and authz each have negative
**and** positive end-to-end tests through the real ASGI stack (`tests/test_hardening.py`).

## Dependency intake record
| Package | Why | Check |
|---|---|---|
| `mcp` | Official MCP Python SDK (Linux Foundation project) | Name verified; required |
| `httpx2` | HTTP client; a hard dependency of `mcp` 2.x | Maintained by Pydantic Services (fork of httpx by its original author); not an extra choice |
| `pydantic` | Schema validation; already a dependency of `mcp` | — |
| `pyjwt[crypto]` | JWT verification for remote mode; brings `cryptography` | Long-established; JWKS cooldown behaviour read in source |

## Deployment checklist
- [ ] Secrets in a secret manager, mounted as files (`SAM_API_KEY_FILE`, `TANGO_API_KEY_FILE`); rotate SAM keys before their 90-day expiry.
- [ ] Egress firewall allows only the hosts in CONNECTIONS.md §1.
- [ ] TLS terminates at a reverse proxy in front of `--transport http`. Set `GOVCON_ALLOWED_HOSTS` to the public hostname.
- [ ] OAuth configured (CONNECTIONS.md §2.4); `GOVCON_ALLOWED_ORIGINS` set to the client origin(s).
- [ ] Run as a non-root user in a read-only container filesystem.
- [ ] Deploy from `requirements-lock.txt` with `--require-hashes`.
- [ ] SAM key has **read public** permission only (see Credential reach).
- [ ] Set `GOVCON_SAM_DAILY_BUDGET` to your key's real daily limit (default 10).
- [ ] Point load-balancer health checks at `/healthz`, not `/mcp` (`/mcp` returns 401 without a token).
