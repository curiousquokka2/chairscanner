# Local setup: SAM.gov key + live test on your own computer

Use this to run the SAM.gov live test from your own machine. The cloud sandbox can't reach api.sam.gov.

**Rules for the key**
- Never paste it into chat, email, a ticket or any file inside the repo.
- Keep it in one file in your home folder that only your user account can read.
- Type it in at a hidden prompt (steps below) so it never lands in your shell history.

You need **Python 3.12 or newer** and **git**. Check with `python3 --version` (Windows: `py --version`).

---

## macOS / Linux

### 1. Save the key (2 minutes)
Open Terminal and run these lines one at a time:

```bash
mkdir -p ~/.secrets && chmod 700 ~/.secrets
read -rs SAMKEY        # paste the key, press Enter (nothing is shown - that's intended)
printf '%s' "$SAMKEY" > ~/.secrets/sam_api_key
unset SAMKEY
chmod 600 ~/.secrets/sam_api_key
```

To confirm it saved without displaying it, run `wc -c ~/.secrets/sam_api_key`. It should show a non-zero character count.

### 2. Get the code
```bash
git clone https://github.com/curiousquokka2/chairscanner.git
cd chairscanner
git checkout claude/custom-connectors-contracting-xsd99w
cd gov-connectors
python3 -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r requirements-lock.txt
pip install --no-deps -e .
```

### 3. Run the SAM.gov live test (uses 1 of your daily SAM calls)
```bash
SAM_API_KEY_FILE=~/.secrets/sam_api_key pytest -m live -k sam -rs
```

---

## Windows (PowerShell 7+)

### 1. Save the key
```powershell
New-Item -ItemType Directory -Force "$HOME\.secrets" | Out-Null
$k = Read-Host "Paste SAM key" -MaskInput
Set-Content -Path "$HOME\.secrets\sam_api_key" -Value $k -NoNewline
Remove-Variable k
icacls "$HOME\.secrets\sam_api_key" /inheritance:r /grant:r "$($env:USERNAME):(R,W)"
```
To confirm it saved, run `(Get-Item "$HOME\.secrets\sam_api_key").Length`. It should show a non-zero number.

On Windows PowerShell 5.1, `-MaskInput` doesn't exist. Install PowerShell 7 from the Microsoft Store, or use
`-AsSecureString` and ask for help converting it.

### 2. Get the code
```powershell
git clone https://github.com/curiousquokka2/chairscanner.git
cd chairscanner
git checkout claude/custom-connectors-contracting-xsd99w
cd gov-connectors
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install --require-hashes -r requirements-lock.txt
pip install --no-deps -e .
```

### 3. Run the SAM.gov live test
```powershell
$env:SAM_API_KEY_FILE = "$HOME\.secrets\sam_api_key"
pytest -m live -k sam -rs
```

---

## Reading the result

| You see | Meaning | Next step |
|---|---|---|
| `1 passed` | Key works and SAM.gov is reachable from your network | Done. Record the date in CONNECTIONS.md |
| `SKIPPED ... SAM_API_KEY not set` | The test didn't find the key file | Check the path in `SAM_API_KEY_FILE` |
| `HTTP 401` / `HTTP 403` + "check the API key" | Key rejected (typo, expired or revoked) | Re-save the key (step 1) or generate a new one at sam.gov → Account Details |
| `HTTP 404` | Same symptom as the cloud sandbox | Tell Claude; the next step is checking SAM.gov's status and change log |
| `local daily budget ... exhausted` | Local safety cap reached (default 10/day) | Wait until 00:00 UTC, or set `GOVCON_SAM_DAILY_BUDGET` to your key's real limit |
| `HTTP 429` | SAM.gov's own daily limit reached | Wait until tomorrow |

## Picking the work back up with Claude
Open a Claude Code session on this repo and branch (`claude/custom-connectors-contracting-xsd99w`), then
say: *"Continue the govcon connectors work. Read gov-connectors/docs/CONNECTIONS.md first."* The project rules
in `CLAUDE.md` load automatically. Tell Claude the test result in words. **Don't paste the key.**

Open items carried over (see CONNECTIONS.md):
1. SAM.gov live test result (this page).
2. Tango key (scope decided: owner-only use).
3. Optional, recommended: a free Socrata app token (CONNECTIONS.md §2.3).
4. Decide whether to update the older `run_scanner.yml` workflow (it probably no longer runs).
5. Accepted risk: rotate the SAM key at its next renewal.
