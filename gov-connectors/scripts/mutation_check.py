"""Mutation check: disable each security control and confirm the suite goes red.

Run from gov-connectors/: python scripts/mutation_check.py
A SURVIVED line means a control has no test proving it. Exit code = survivors.
"""
import pathlib, subprocess, sys
S = "src/govcon_mcp/"
MUTATIONS = [
  ("host allowlist", S+"safehttp.py", 'if parts.scheme != "https" or host not in self.allowed_hosts or parts.username or parts.password:', 'if False:'),
  ("no-redirect", S+"safehttp.py", 'if 300 <= status < 400:', 'if False:'),
  ("error redaction", S+"safehttp.py", 'raise UpstreamError(self.name, status, self.redact(raw[:500].decode("utf-8", "replace")))', 'raise UpstreamError(self.name, status, raw[:500].decode("utf-8", "replace"))'),
  ("body redaction", S+"safehttp.py", 'json.loads(self.redact(raw.decode("utf-8")))', 'json.loads(raw.decode("utf-8"))'),
  ("size cap", S+"safehttp.py", 'if size > self._max_bytes:', 'if False:'),
  ("daily budget", S+"safehttp.py", 'self._budget.take(self.name)  #', 'pass  #'),
  ("SoQL value regex", S+"connectors/sled.py", 'if not _SAFE_VALUE.match(value):', 'if False:'),
  ("SLED field allowlist", S+"connectors/sled.py", 'if field not in d.filterable:', 'if False:'),
  ("SBIR PII strip", S+"connectors/sbir.py", '"women_owned", "number_employees"', '"women_owned", "poc_email", "pi_phone", "number_employees"'),
  ("SAM forbidden chars", S+"validation.py", 'value = _SAM_FORBIDDEN.sub(" ", value).strip()', 'value = value.strip()'),
  ("JWT audience", S+"auth.py", 'audience=self.audience, issuer', 'options_aud=None, issuer'),
  ("JWT scope check", S+"auth.py", 'if not self.required_scopes.issubset(scopes):', 'if False:'),
  ("non-loopback refusal", S+"server.py", '    elif not loopback:', '    elif False:'),
  ("tango reserved filters", S+"connectors/tango.py", 'if k in reserved:', 'if False:'),
]
bad = 0
for name, path, old, new in MUTATIONS:
    p = pathlib.Path(path); orig = p.read_text()
    if old not in orig:
        print(f"?? {name}: anchor not found"); bad += 1; continue
    p.write_text(orig.replace(old, new, 1))
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"], capture_output=True, text=True)
    finally:
        p.write_text(orig)
    killed = r.returncode != 0
    bad += not killed
    print(("KILLED   " if killed else "SURVIVED ") + name)
print("survivors/missing:", bad)
sys.exit(bad)
