# Project rules

## Always read all the documentation before acting (general rule)
This applies to anything you use, not only APIs. That includes libraries and SDKs, CLIs, frameworks,
cloud services, MCP servers and connectors, CI actions, data sources and their terms of use.

**New to this project → read first, review, then start.** Before first use of anything new:
1. Read all of its official documentation, not just the API reference or the first screen. That
   covers overview, terms of use / acceptable-use policy, auth and permission model, data handling
   and privacy, limits and quotas, pricing, security guidance, known issues, deprecations and the
   change log.
2. Write up any **security or use concerns** and raise them for human review **before starting
   work**. Examples: what a credential reaches beyond this task, PII/CUI exposure, licensing or
   terms that restrict use, cost, quotas, maintenance or outage notices, unmaintained or suspicious
   packages. Do not proceed on a flagged concern until a human has answered it.

**Already in use → still read it.** Having started with a service is not a reason to skip its docs.
Before changing how it is used, or adding a feature that touches it, read the relevant docs in
full again and check the change log for anything new since the last read. Raise any new concern
the same way.

**Every time:**
1. Read the official documentation for everything involved in full, not just the first screen.
   For APIs that covers auth, required params, formats, limits/quotas, pagination, errors,
   deprecations and the change log.
2. Prefer primary sources (the agency's own docs, OpenAPI spec, or changelog) over blog posts,
   SDK READMEs or memory.
3. Record what you verified in `gov-connectors/docs/CONNECTIONS.md` (for external services) or
   `gov-connectors/docs/SECURITY.md` (for dependencies and tooling): the doc URL, the date read, any
   concerns raised and how they were resolved, and anything left unverified (mark it **unverified** and say how to confirm it).
4. Do not guess a parameter, field or response shape. If the docs do not pin it down, say so, code
   defensively, and add a live test that confirms it.
5. Re-read the docs when an upstream returns something unexpected, before changing code.

## Other conventions
- Connector work lives in `gov-connectors/`; keep the existing `scanner.py` untouched unless asked.
- Every upstream host must be in its connector's allowlist and in CONNECTIONS.md.
- Never commit secrets; keys come from env vars or `*_FILE` mounts.
