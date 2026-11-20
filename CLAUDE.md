# Project rules

## Always read the API documentation before acting (general rule)
Before writing, changing or calling code against any external API:
1. Read the official documentation for every endpoint involved in full, not just the first screen.
   That covers auth, required params, formats, limits/quotas, pagination, errors, deprecations and
   the change log.
2. Prefer primary sources (the agency's own docs, OpenAPI spec, or changelog) over blog posts,
   SDK READMEs or memory.
3. Record what you verified in `gov-connectors/docs/CONNECTIONS.md`: the doc URL, the date read, and
   anything left unverified (mark it **unverified** and say how to confirm it).
4. Do not guess a parameter, field or response shape. If the docs do not pin it down, say so, code
   defensively, and add a live test that confirms it.
5. Re-read the docs when an upstream returns something unexpected, before changing code.

## Other conventions
- Connector work lives in `gov-connectors/`; keep the existing `scanner.py` untouched unless asked.
- Every upstream host must be in its connector's allowlist and in CONNECTIONS.md.
- Never commit secrets; keys come from env vars or `*_FILE` mounts.
