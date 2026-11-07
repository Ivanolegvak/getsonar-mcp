<!-- mcp-name: io.github.Ivanolegvak/sonar-mcp -->

# getsonar-mcp

[![PyPI version](https://img.shields.io/pypi/v/getsonar-mcp.svg)](https://pypi.org/project/getsonar-mcp/)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-listed-4f46e5)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.Ivanolegvak/sonar-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

MCP server for [SONAR](https://getsonar.report/integrations): **KYB due diligence on vendors, partners and resellers**, callable from your AI assistant.

Ask Claude, Cursor or Windsurf whether a company exists and is in good standing, or to screen it, and it gets back the official register record, sanctions and PEP matches, ICIJ Offshore Leaks hits and adverse media, each finding naming the kind of source it came from.

> SONAR is a due-diligence aid built on public records. It is **not** a regulated AML/KYC provider and its output is not a compliance decision: a human reviews the findings.

## Features

- **Company register lookup**: a live search of the official register in about a second (GB, FR, CZ, SK, NO, FI, CH, EE, LV, US states; PL, BE, BR by number): exists or not, active, good standing, legal form, address, VAT number, previous names, officers and filings. €0.01 only when the company is found
- **Company registries in the KYB check**: official company registries in 10+ countries for legal name, number, status, address, officers and owners
- **Sanctions and PEP screening**: native OFAC, UN, UK OFSI and Swiss SECO lists plus the OpenSanctions aggregator
- **ICIJ Offshore Leaks**: Panama, Paradise and Pandora Papers, Bahamas Leaks
- **Regulatory registers**: UK FCA Register, UK Disqualified Directors, The Gazette insolvency notices
- **Adverse media**: 10-year lookback on news, complaints and reviews
- **Three call shapes**: a register lookup (about 1 s), structured screening findings (30-90 s; the tools poll the API's 202 + poll URL for you) or a full written report (async, about 3 min)

Works with **Claude Desktop**, **Claude Code**, **Cursor**, **Windsurf** and any other [Model Context Protocol](https://modelcontextprotocol.io) client. Listed in the official MCP Registry as `io.github.Ivanolegvak/sonar-mcp`.

## Pricing

The API is pay per call:

| Call | Price |
|---|---|
| Company lookup (`company_lookup`, `company_officers`) | €0.01 when the company is found, free when not; the first 100 found are free |
| `/findings` (`kyb_findings`, `adverse_media`) | €0.50 |
| `/run` (`kyb_run_submit`) | €6.00 |
| `check_report_status`, `account_balance` | free |

**Your first API call is free** (a findings or report call; lookups have their own 100 free). After that, calls are paid from a prepaid balance: top up from €5 at [getsonar.report/developer/keys](https://getsonar.report/developer/keys). Plans and the web app's free tier are on [getsonar.report/pricing](https://getsonar.report/pricing).

## Get an API key

1. Sign up at [getsonar.report](https://getsonar.report)
2. Open [Developer → API keys](https://getsonar.report/developer/keys)
3. Click **Create API Key** and copy the `sk-sonar-...` key

## Installation

You need [`uv`](https://docs.astral.sh/uv/getting-started/installation/) (it provides `uvx`). Nothing else to install: `uvx getsonar-mcp` fetches and runs the latest release. With pipx instead: `pipx install getsonar-mcp`, then use `getsonar-mcp` as the command.

The key goes in the `SONAR_API_KEY` environment variable of the server process.

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "sonar": {
      "command": "uvx",
      "args": ["getsonar-mcp"],
      "env": {
        "SONAR_API_KEY": "sk-sonar-YOUR_KEY_HERE"
      }
    }
  }
}
```

Restart Claude Desktop. The seven SONAR tools appear in the tools menu. If they don't, Claude Desktop may not find `uvx` on its PATH: replace `"uvx"` with the full path that `which uvx` prints (e.g. `/Users/you/.local/bin/uvx`).

### Claude Code

```bash
claude mcp add sonar --env SONAR_API_KEY=sk-sonar-YOUR_KEY_HERE -- uvx getsonar-mcp
```

Add `--scope user` to make it available in every project. Check it with `claude mcp list`.

### Cursor

Edit `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project):

```json
{
  "mcpServers": {
    "sonar": {
      "command": "uvx",
      "args": ["getsonar-mcp"],
      "env": {
        "SONAR_API_KEY": "sk-sonar-YOUR_KEY_HERE"
      }
    }
  }
}
```

### Windsurf

Edit `~/.codeium/windsurf/mcp_config.json` (or Windsurf Settings → Cascade → MCP servers → View raw config):

```json
{
  "mcpServers": {
    "sonar": {
      "command": "uvx",
      "args": ["getsonar-mcp"],
      "env": {
        "SONAR_API_KEY": "sk-sonar-YOUR_KEY_HERE"
      }
    }
  }
}
```

Other clients (Continue.dev, Zed, Cline, ...) take the same command, args and env; see your client's MCP docs for where the config lives.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SONAR_API_KEY` | (required) | Your `sk-sonar-...` API key (or an `sk-sonar-test-...` sandbox key, see below) |
| `SONAR_API_BASE` | `https://api.getsonar.report` | Override for staging or self-hosted SONAR |
| `SONAR_API_TIMEOUT` | `120` | Per-request timeout in seconds |
| `SONAR_MCP_LOG_LEVEL` | `INFO` | `DEBUG` for verbose logs (stderr) |

## Tools

| Tool | What it does | Price |
|---|---|---|
| `company_lookup` | Register check: does the company exist, is it active and in good standing | €0.01 if found |
| `company_officers` | A company's officers from its register, current and former | €0.01 if found |
| `kyb_findings` | KYB screening: sanctions, PEP, owners, adverse media and the register | €0.50 |
| `kyb_run_submit` | Submit a full KYB report, returns a `run_id` | €6.00 |
| `adverse_media` | Negative news, complaints and reviews | €0.50 |
| `check_report_status` | Poll a report submitted with `kyb_run_submit` | free |
| `account_balance` | Balance, free calls and free lookups remaining | free |

All tools return Markdown for the model to read. Which one to use:

- "Does this company exist / is it registered / is it active?": `company_lookup` (€0.01)
- "Who are its directors?": `company_lookup` with `include: ["officers"]`, or `company_officers` (€0.01)
- "Screen it for sanctions, PEP, offshore leaks or bad press": `kyb_findings` (€0.50)
- "Give me a full written KYB report": `kyb_run_submit` then `check_report_status` (€6.00)

### `company_lookup`

Input:

```json
{ "country": "GB", "company_name": "Tesco PLC", "include": ["officers", "filings"] }
```

`country` (ISO code) is required, plus `company_name` or `registration_number` (a number is matched exactly and decides alone; PL, BE and BR take a number only). `state` is required for the US (NY, CO, OR, CT, TX, PA, FL, IA, DC). `include` is optional and free: `officers` (GB, CZ, SK, NO, FR) and `filings` (GB, FR) of the found company.

The name rule is strict: case, punctuation, accents and the spelling of the legal form are set aside, any other difference is another company, so a look-alike name is `NOT_FOUND`.

Output: a headline, then the API's full JSON answer (every field, nothing dropped):

```markdown
# Company lookup: Tesco PLC (GB): **FOUND**
- TESCO PLC (00445790): active (register: active)
- Good standing: yes (active, no default or insolvency marker on the register)
- Charged: €0.01 · Free lookups left: 0

Full answer:
{"query": ..., "status": "FOUND", "matches": [{"name": "TESCO PLC", "good_standing": true, "officers": [...], "filings": [...], ...}], "truncated": null, "coverage_note": null, ...}
```

`good_standing` is `false` when the company is closed or the register marks a default or insolvency (GB: accounts or confirmation statement overdue, strike-off pending), and `null` where the register publishes no such markers. `truncated: true` (FR) means the register holds more companies of the name than it returned: search by number. `coverage_note` (US) says what the state register holds, so a `NOT_FOUND` reads for what it is.

### `company_officers`

Input:

```json
{ "country": "GB", "registration_number": "00445790" }
```

Output: a headline (current and former officer counts, price) and the full JSON: name, role, person or company, `appointed_on`, `resigned_on`. GB, CZ, SK, NO, FR. Priced like a lookup.

### `kyb_findings`

Input:

```json
{ "company_name": "Tesco PLC", "website": "https://www.tesco.com", "country": "GB", "registration_number": "00445790" }
```

`company_name` is required. Pass `country` (and `state` for the US): without it no company register is searched and the answer says `NOT_SEARCHED`. `registration_number` and `vat_number` are optional. `website` is optional but strongly recommended: it separates the company from unrelated ones sharing the name.

Output (abridged, values illustrative):

```markdown
# KYB Screening: Tesco PLC
Sources checked: 42 · Processing time: 41250ms

## Company register: **FOUND** (GB)
- Registered name: TESCO PLC
- Number: 00445790
- Status: active
- Good standing: yes (active, no default or insolvency marker on the register)

**Found data**: corporate_registration, directors_officers, adverse_media
**Checked, clean** (the check ran and returned nothing about the company): sanctions_screening, offshore_leaks

## Corporate Registration (confidence: HIGH)
- **TESCO PLC (00445790), active**
  Public limited company
  Source: company_register
```

Each finding names the kind of source (`company_register`, `sanctions_lists`, `offshore_records`, `news_search`, ...); news articles keep their link.

### `kyb_run_submit`

Input: same as `kyb_findings`. Output:

```markdown
Report submitted.
- Run ID: `3f6c...`
- Status: pending
- Estimated time: 90 seconds

Call `check_report_status` with run_id='3f6c...' and agent_type='kyb-diligence' in 30-60 seconds to get the result.
```

### `check_report_status`

Input:

```json
{ "run_id": "3f6c...", "agent_type": "kyb-diligence" }
```

`agent_type` is `kyb-diligence` (default) or `adverse-media`. While the report runs it answers `Report status: running. Still processing, check again in 15-30 seconds.`; when done it returns a compact summary: overall verdict and risk level, company details, a PASS / REVIEW / FLAG table of checks, risk flags, directors and sanctions coverage.

### `adverse_media`

Input: same as `kyb_findings`. Output: the same Markdown shape as `kyb_findings`, limited to news, complaints and review sites (no sanctions or PEP screening).

### `account_balance`

Input: none. Output:

```markdown
# Account usage: 2026-11
- Calls this month: **0**
- Free trial calls remaining: **1** (granted once at signup)
- Pre-paid balance: **€5.00**
- Free company lookups remaining: **100** (spent only when a lookup finds the company)
```

## Example prompts

> "Is Tesco PLC an active UK company in good standing? Who are its directors?"

The model calls `company_lookup` with `country: "GB"` and `include: ["officers"]`: one call, €0.01.

> "Run a KYB check on Tesco PLC (tesco.com) and tell me if anything needs a closer look."

The model calls `kyb_findings`, reads the structured findings and points out sanctions, register or adverse-media hits with their kind of source.

> "Get a full KYB report on Wise Payments Limited and summarise it when it's done."

The model calls `kyb_run_submit`, then `check_report_status` until the report is complete.

> "How many free trial calls do I have left?"

The model calls `account_balance`.

## Verify your install

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) starts the server and lists its tools:

```bash
SONAR_API_KEY=sk-sonar-YOUR_KEY_HERE npx @modelcontextprotocol/inspector uvx getsonar-mcp
```

Listing tools works without a key; calling one needs a valid key.

## Test without paying (sandbox key)

Create a test key (`sk-sonar-test-...`) on [Developer → API keys](https://getsonar.report/developer/keys) and put it in `SONAR_API_KEY`. It answers `company_lookup`, `company_officers` and `account_balance` with fixed, made-up scenarios, never calls a register and is never charged:

| `company_name` | Number | Answer |
|---|---|---|
| SONAR Sandbox Found Ltd | 1 | FOUND, active |
| SONAR Sandbox Dissolved Ltd | 2 | FOUND, inactive |
| SONAR Sandbox Ambiguous Ltd | | AMBIGUOUS |
| SONAR Sandbox Unavailable Ltd | 3 | 503, register unavailable |
| anything else | any other | NOT_FOUND |

The number must still be in the country's format (for GB, `00000001`). A test key cannot run `kyb_findings`, `adverse_media` or `kyb_run_submit` (403 `SANDBOX_KEY`).

## Use the API without MCP

The MCP server is a thin client over the SONAR REST API. To call it directly:

```bash
export SONAR_API_KEY=sk-sonar-YOUR_KEY_HERE

# Register lookup: about 1 s, €0.01 when found (100 free), free when not
curl -X POST 'https://api.getsonar.report/v1/companies/lookup' \
  -H "X-API-Key: $SONAR_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"country":"GB","company_name":"Tesco PLC","include":["officers"]}'

# Structured findings: 30-90 s, €0.50. 200 within ?wait= s (default 120),
# else 202 {"job_id", "poll_url"}: GET the poll_url until 200
curl -X POST 'https://api.getsonar.report/v1/agents/kyb-diligence/findings' \
  -H "X-API-Key: $SONAR_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"company_name":"Tesco PLC","website":"https://www.tesco.com","country":"GB"}'

# Full report: async, about 3 min, €6.00; returns {"run_id": ..., "status": "pending"}
curl -X POST 'https://api.getsonar.report/v1/agents/kyb-diligence/run' \
  -H "X-API-Key: $SONAR_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"company_name":"Tesco PLC","website":"https://www.tesco.com"}'

# Poll until status is "completed"
curl 'https://api.getsonar.report/v1/agents/kyb-diligence/run/RUN_ID' -H "X-API-Key: $SONAR_API_KEY"

# Usage, balance and free trial calls left
curl 'https://api.getsonar.report/v1/usage' -H "X-API-Key: $SONAR_API_KEY"
```

Agents: `kyb-diligence` (registries, sanctions, PEP, UBOs, adverse media) and `adverse-media` (negative news only). The `website` field must be an `http://` or `https://` URL. Full OpenAPI spec: [api.getsonar.report/docs](https://api.getsonar.report/docs). Developer guide: [getsonar.report/developers](https://getsonar.report/developers).

## Troubleshooting

**Tools don't appear**: check the config file is valid JSON, restart the client, and run `uvx --version` in a terminal to confirm `uv` is installed.

**`401 Unauthorized`**: `SONAR_API_KEY` is missing or wrong. Check it at [getsonar.report/developer/keys](https://getsonar.report/developer/keys).

**`402 Payment Required`**: your free first call (or your 100 free lookups) is used and your balance is too low. Top up from €5 at [getsonar.report/developer/keys](https://getsonar.report/developer/keys).

**`403 SANDBOX_KEY`**: a test key only runs `company_lookup`, `company_officers` and `account_balance`. Use a live key for screening and reports.

**`429`**: rate limit. `kyb_findings`, `adverse_media` and `kyb_run_submit` allow 10 calls a minute per key by default; lookups allow at least 120.

**`registry_match: NOT_SEARCHED`** in `kyb_findings`: pass `country` (and `state` for the US).

**Timeouts**: raise `SONAR_API_TIMEOUT`. A full report can take 3+ minutes; poll with `check_report_status` rather than waiting on one call.

**`uvx getsonar-mcp` runs an old version**: uvx caches environments. Run `uvx getsonar-mcp@latest` once, or `uv cache clean getsonar-mcp`.

**Wrong company in the results**: pass `country` and `registration_number` (or `website`). Short brand names collide with unrelated companies in news search; SONAR drops those collisions when it knows the domain.

## Development

```bash
uv sync
uv run pytest        # stdio smoke test and formatter tests against a fake API, no network
```

Maintainers: [ARCHITECTURE.md](./ARCHITECTURE.md) covers the module layout and the stdio / HTTP transports; [DIRECTORIES.md](./DIRECTORIES.md) covers releasing and listing in MCP directories.

## Support

Email **ivan@getsonar.report** or open an issue on [GitHub](https://github.com/Ivanolegvak/getsonar-mcp/issues).

## License

MIT, see [LICENSE](LICENSE).
