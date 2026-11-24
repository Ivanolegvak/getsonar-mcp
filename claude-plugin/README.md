# SONAR KYB plugin for Claude

KYB due diligence on vendors, partners and resellers, from inside Claude. Ask whether a company exists and is in good standing, who its directors are, or to screen it, and Claude answers from public records: official company registries in 10+ countries, sanctions and PEP lists, ICIJ Offshore Leaks records and 10 years of adverse media. Each finding names the kind of source it came from.

> SONAR is a due-diligence aid built on public records. It is **not** a regulated AML/KYC provider and its output is not a compliance decision: a human reviews the findings.

## What the plugin does

The plugin adds one remote MCP server, SONAR's hosted server at `https://sonar-mcp.sonar-mcp-remote.workers.dev/mcp` (Streamable HTTP). It runs nothing on your computer, installs no packages and holds no API key.

The first time Claude uses it, your client opens a browser window: select **Continue** on the consent page, sign in to your SONAR account and confirm with **Connect**. SONAR then creates an API key for that connection (named "MCP connector: <app>", listed and revocable under [Developer, API keys](https://getsonar.report/developer/keys)) and the client keeps only an OAuth token. In claude.ai and Cowork, connect it from the plugin's **Connectors** tab; Claude Code connects directly (check with `/mcp`).

## Tools and prices

| Tool | What it answers | Price |
|---|---|---|
| `company_lookup` | Does the company exist, is it active and in good standing | €0.01 when found, free when not; the first 100 found are free |
| `company_officers` | The company's officers from its register | €0.01 when found |
| `kyb_findings` | Sanctions, PEP, offshore-leak, ownership and adverse-media screening | €0.50 |
| `adverse_media` | Adverse media only: news, complaints and review sites | €0.50 |
| `kyb_run_submit` | A full written KYB report | €6.00 |
| `check_report_status` | Status of a report run | free |
| `account_balance` | Your prepaid balance | free |

Your first findings or report call is free. After that, calls are paid from a prepaid balance that you top up at [getsonar.report/developer/keys](https://getsonar.report/developer/keys).

## Data and privacy

The plugin sends the arguments of each tool call (company name, country, registration number, website, VAT number, run IDs) to the hosted server, a Cloudflare Worker run by SONAR, which forwards them to the SONAR API at `api.getsonar.report`. Nothing goes to any other destination. The Worker keeps only OAuth records and no report data. Full policy: [getsonar.report/privacy](https://getsonar.report/privacy). Terms: [getsonar.report/terms](https://getsonar.report/terms).

## Support

Email ivan@getsonar.report or open an issue on [GitHub](https://github.com/Ivanolegvak/getsonar-mcp/issues). The plugin is MIT licensed; the source of the local server and full documentation are in the [repository README](https://github.com/Ivanolegvak/getsonar-mcp#readme).
