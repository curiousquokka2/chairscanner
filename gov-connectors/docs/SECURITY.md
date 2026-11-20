# Security Model (zero trust)

Assume every boundary is hostile: the calling model (prompt injection), upstream APIs (compromise,
poisoned records), the network, and the deployment host.

| Threat | Control | Where |
|---|---|---|
| Model tricked into calling arbitrary URLs (SSRF / data exfiltration) | Every connector has its own exact-host HTTPS allowlist. Tools take typed parameters, never URLs or paths. Tango resources and SLED datasets are allowlisted enumerations. | `http.py::_check_url`, `connectors/*` |
| API key leakage | Keys are read from env or `*_FILE` secret mounts into `SecretStr`. Each key goes only to its own connector's client, is injected at send time, is left out of cache keys, and is scrubbed from error text **and** response bodies. Keys go in headers where the upstream supports it (Tango, Socrata). SAM.gov requires a query param, so logs must never record SAM URLs. | `config.py`, `http.py` |
| Redirect-based key exfiltration | `follow_redirects=False`; any 3xx is an error. | `http.py` |
| Injection into upstream query languages | Pydantic patterns on IDs, dates and codes. SAM's forbidden characters are stripped. SoQL is built server-side from allowlisted fields, with a strict value regex and quote escaping. The model cannot send raw SoQL. | `validation.py`, `sled.py` |
| Prompt injection via returned records | Responses are wrapped in an envelope with `untrusted_content: true`. Server instructions tell the agent never to follow instructions found in data. Long text is truncated. | `validation.py::envelope`, `server.py` |
| Resource exhaustion / quota burn | Timeouts, an 8 MB response cap, JSON-only bodies, per-connector token-bucket rate limits, bounded retries honouring `Retry-After`, a TTL cache (≥1 h for SAM), and capped page sizes. | `http.py` |
| PII over-collection | Output allowlists: SAM points of contact, SBIR phone/email, and city contact names/emails are dropped. | connectors |
| Unauthenticated remote access | HTTP transport binds loopback by default. A non-loopback bind **refuses to start** without OAuth. When enabled: JWT with asymmetric algorithms only, JWKS over HTTPS, and required `iss`/`aud`/`exp`/`sub` plus scope. DNS-rebinding protection is on, with Host and Origin allowlists. Stateless HTTP (no server-side sessions). | `server.py`, `auth.py` |
| Error-message leakage | Only `GovconError` (sanitised) messages reach the model; other exceptions become generic errors. Logs go to stderr and never include params. | `errors.py`, `server.py` |
| Write actions | None exist. Every tool is annotated `readOnlyHint=True`. | `connectors/base.py` |
| Supply chain | Few dependencies, major-version bounds. **Before production:** generate a hash-pinned lock file (`uv lock` / `pip-compile --generate-hashes`), enable Dependabot, and run `pip-audit`. | `pyproject.toml` |

## Deployment checklist
- [ ] Secrets in a secret manager, mounted as files (`SAM_API_KEY_FILE`, `TANGO_API_KEY_FILE`); rotate SAM keys before their 90-day expiry.
- [ ] Egress firewall allows only the hosts in CONNECTIONS.md §1.
- [ ] TLS terminates at a reverse proxy in front of `--transport http`. Set `GOVCON_ALLOWED_HOSTS` to the public hostname.
- [ ] OAuth configured (CONNECTIONS.md §2.4); `GOVCON_ALLOWED_ORIGINS` set to the client origin(s).
- [ ] Run as a non-root user in a read-only container filesystem.
- [ ] Hash-pinned lock file plus `pip-audit` in CI.
