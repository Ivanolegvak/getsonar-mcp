<!-- mcp-name: io.github.Ivanolegvak/sonar-mcp -->

# getsonar-mcp

[![PyPI version](https://img.shields.io/pypi/v/getsonar-mcp.svg)](https://pypi.org/project/getsonar-mcp/)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-listed-4f46e5)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.Ivanolegvak/sonar-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

MCP server for [SONAR](https://getsonar.report/integrations): **KYB due diligence on vendors, partners and resellers**, callable from your AI assistant.

Ask Claude, Cursor or Windsurf to check a company and it gets back registry records, sanctions and PEP matches, ICIJ Offshore Leaks hits and adverse media, each with a link to the source.

> SONAR is a due-diligence aid built on public records. It is **not** a regulated AML/KYC provider and its output is not a compliance decision: a human reviews the findings.

## Features

- **Company registries**: 13 national business registries (UK Companies House and 12 more) for legal name, number, status, address and officers
- **Sanctions and PEP screening**: native OFAC, UN, UK OFSI and Swiss SECO lists plus the OpenSanctions aggregator
- **ICIJ Offshore Leaks**: Panama, Paradise and Pandora Papers, Bahamas Leaks
- **Regulatory registers**: UK FCA Register, UK Disqualified Directors, The Gazette insolvency notices
- **Adverse media**: 10-year lookback on news, complaints and reviews
- **Two call shapes**: fast structured findings (sync, 30-90 s) or a full written report (async, about 3 min)

Works with **Claude Desktop**, **Claude Code**, **Cursor**, **Windsurf** and any other [Model Context Protocol](https://modelcontextprotocol.io) client. Listed in the official MCP Registry as `io.github.Ivanolegvak/sonar-mcp`.

## Pricing

The API is pay per call:

| Call | Price |
|---|---|
| `/findings` (`kyb_findings`, `adverse_media`) | €0.40 |
| `/run` (`kyb_run_submit`) | €2.00 |
| `check_report_status`, `account_balance` | free |

**Your first API call is free** (any endpoint). After that, calls are paid from a prepaid balance: top up from €5 at [getsonar.report/developer/keys](https://getsonar.report/developer/keys). Plans and the web app's free tier are on [getsonar.report/pricing](https://getsonar.report/pricing).

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

Restart Claude Desktop. The five SONAR tools appear in the tools menu.

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
| `SONAR_API_KEY` | (required) | Your `sk-sonar-...` API key |
| `SONAR_API_BASE` | `https://api.getsonar.report` | Override for staging or self-hosted SONAR |
| `SONAR_API_TIMEOUT` | `120` | Per-request timeout in seconds |
| `SONAR_MCP_LOG_LEVEL` | `INFO` | `DEBUG` for verbose logs (stderr) |

## Tools

| Tool | What it does | Price |
|---|---|---|
| `kyb_findings` | Fast KYB check: structured findings with sources | €0.40 |
| `kyb_run_submit` | Submit a full KYB report, returns a `run_id` | €2.00 |
| `adverse_media` | Negative news, complaints and reviews | €0.40 |
| `check_report_status` | Poll a report submitted with `kyb_run_submit` | free |
| `account_balance` | Balance and free trial calls remaining | free |

All tools return Markdown for the model to read.

### `kyb_findings`

Input:

```json
{ "company_name": "Tesco PLC", "website": "https://www.tesco.com" }
```

`company_name` is required. `website` is optional but strongly recommended: it separates the company from unrelated ones sharing the name.

Output (abridged, values illustrative):

```markdown
# KYB Quick Lookup: Tesco PLC
Sources checked: 42 · Processing time: 41250ms
**Found data**: registry, regulatory, adverse_media
**Checked, clean** (no findings — collector ran): sanctions, offshore_leaks

## Registry (confidence: HIGH)
- **TESCO PLC (00445790), active**
  Public limited company
  Source: https://find-and-update.company-information.service.gov.uk/company/00445790
```

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

`agent_type` is `kyb-diligence` (default) or `adverse-media`. While the report runs it answers `Report status: running. Still processing — check again in 15-30 seconds.`; when done it returns a compact summary: overall verdict and risk level, company details, a PASS / REVIEW / FLAG table of checks, risk flags, directors and sanctions coverage.

### `adverse_media`

Input: same as `kyb_findings`. Output: the same Markdown shape as `kyb_findings`, limited to news, complaints and review sites (no sanctions or PEP screening).

### `account_balance`

Input: none. Output:

```markdown
# Account usage — 2026-10
- Calls this month: **0**
- Free trial calls remaining: **1** (granted once at signup)
- Pre-paid balance: **€5.00**
```

## Example prompts

> "Run a KYB check on Tesco PLC (tesco.com) and tell me if anything needs a closer look."

The model calls `kyb_findings`, reads the structured findings and points out sanctions, register or adverse-media hits with their sources.

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

## Use the API without MCP

The MCP server is a thin client over the SONAR REST API. To call it directly:

```bash
export SONAR_API_KEY=sk-sonar-YOUR_KEY_HERE

# Structured findings: sync, 30-90 s, €0.40
curl -X POST 'https://api.getsonar.report/v1/agents/kyb-diligence/findings' \
  -H "X-API-Key: $SONAR_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"company_name":"Tesco PLC","website":"https://www.tesco.com"}'

# Full report: async, about 3 min, €2.00; returns {"run_id": ..., "status": "pending"}
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

**`402 Payment Required`**: your free first call is used and your balance is €0. Top up from €5 at [getsonar.report/developer/keys](https://getsonar.report/developer/keys).

**Timeouts**: raise `SONAR_API_TIMEOUT`. A full report can take 3+ minutes; poll with `check_report_status` rather than waiting on one call.

**`uvx getsonar-mcp` runs an old version**: uvx caches environments. Run `uvx getsonar-mcp@latest` once, or `uv cache clean getsonar-mcp`.

**Wrong company in the results**: pass `website`. Short brand names collide with unrelated companies in news search; SONAR drops those collisions when it knows the domain.

## Development

```bash
uv sync
uv run pytest        # stdio smoke test against a fake API, no network
```

Maintainers: [ARCHITECTURE.md](./ARCHITECTURE.md) covers the module layout and the stdio / HTTP transports; [DIRECTORIES.md](./DIRECTORIES.md) covers releasing and listing in MCP directories.

## Support

Email **ivan@getsonar.report** or open an issue on [GitHub](https://github.com/Ivanolegvak/getsonar-mcp/issues).

## License

MIT, see [LICENSE](LICENSE).
