# getsonar-mcp: release and directory listings

Maintainer runbook. Every step here publishes something public, so a
human (Ivan) runs it; agents only prepare the files. Order matters: each
directory reads from the step before it.

| File | Read by |
|---|---|
| `pyproject.toml`, `README.md` (with the `mcp-name` comment) | PyPI; the MCP Registry checks the comment to prove package ownership |
| `server.json` | Official MCP Registry (`mcp-publisher`), and everything that syncs from it (PulseMCP, GitHub MCP registry, VS Code) |
| `glama.json` | Glama: lets the listed GitHub user claim the server |
| `manifest.json` + `.mcpbignore` | MCPB bundle (`mcpb pack`) for Smithery's local-server flow and one-click Claude Desktop install |
| `smithery.yaml` | Classic Smithery stdio config; Glama and older tooling still read it |
| `LICENSE` | MIT; every directory shows it |
| `scripts/snapshot-public-mirror.sh` | Builds the public source mirror (the monorepo is private) |

The version lives in four places and `tests/test_stdio_smoke.py::test_version_is_consistent`
fails if they drift: `src/getsonar_mcp/__init__.py`, `pyproject.toml`,
`server.json` (twice), `manifest.json` (version and the pinned `uvx` arg).

## 0. Before any release

```bash
cd mcp-server
uv sync && uv run pytest -q            # stdio smoke test, fake API, no network
mcp-publisher validate                 # server.json against the live registry schema
npx @anthropic-ai/mcpb@2.1.2 validate manifest.json
```

## 1. Public source mirror (GitHub) — prerequisite for Glama, mcp.so, Smithery, awesome lists

1. On github.com (account `Ivanolegvak`) create an empty **public** repo `getsonar-mcp`
   (no README/license; description "MCP server for SONAR: KYB due diligence for AI agents",
   website `https://getsonar.report/integrations`, topics `mcp`, `mcp-server`, `kyb`,
   `due-diligence`, `sanctions-screening`).
2. `mcp-server/scripts/snapshot-public-mirror.sh /tmp/getsonar-mcp` (one commit, no monorepo history,
   aborts on anything key-shaped), review `git -C /tmp/getsonar-mcp show --stat`, then run the two
   push commands it prints.
3. Later releases: clone the mirror and pass the clone's path to the same script.

`server.json`, `manifest.json` and `pyproject.toml` already point at
`https://github.com/Ivanolegvak/getsonar-mcp`, so do this before step 2.

## 2. PyPI — `getsonar-mcp` 0.2.0

PyPI is still on 0.1.9, which advertises the frozen competitive-intelligence tools.

```bash
cd mcp-server
rm -rf dist && uv build
uv publish            # needs a PyPI API token for getsonar-mcp (UV_PUBLISH_TOKEN), never commit it
uvx --refresh --from getsonar-mcp==0.2.0 python -c "import getsonar_mcp; print(getsonar_mcp.__version__)"
```

## 3. Official MCP Registry — `io.github.Ivanolegvak/sonar-mcp`

Needs step 2 (the registry fetches the 0.2.0 README from PyPI and looks for
`<!-- mcp-name: io.github.Ivanolegvak/sonar-mcp -->`).

```bash
cd mcp-server
mcp-publisher login github     # browser device flow as Ivanolegvak
mcp-publisher publish          # reads server.json
curl -s 'https://registry.modelcontextprotocol.io/v0/servers?search=io.github.Ivanolegvak/sonar-mcp' | grep -o '"version":"[^"]*"' | tail -1
```

PulseMCP and the GitHub MCP registry ingest from here; no separate submission.

## 4. Glama — glama.ai/mcp/servers

Needs step 1.

1. Sign in at https://glama.ai with GitHub (`Ivanolegvak`).
2. https://glama.ai/mcp/servers → **Add Server** → `https://github.com/Ivanolegvak/getsonar-mcp`.
3. When indexed, open the server page → **Claim** (works because `glama.json` lists `Ivanolegvak`).
4. In the server's Dockerfile / build settings set the start command to `uvx getsonar-mcp` (stdio) and
   `SONAR_API_KEY` as a placeholder env var; Glama's inspection only lists tools, which works without
   a real key.
5. Copy the Glama score badge Markdown for step 5.

## 5. awesome-mcp-servers (punkpeye) — PR

Needs step 4 (the list asks for a Glama listing). The fork `Ivanolegvak/awesome-mcp-servers` exists;
sync it first. Add under **Finance & Fintech**, alphabetical:

```markdown
- [Ivanolegvak/getsonar-mcp](https://github.com/Ivanolegvak/getsonar-mcp) 🐍 ☁️ - KYB due diligence on vendors, partners and resellers: 13 national business registries, sanctions and PEP screening, ICIJ Offshore Leaks and 10-year adverse media, with a source link for every finding. Pay per call, first call free.
```

PR title: `Add getsonar-mcp (KYB due diligence)`. This replaces the copy in
`docs/marketing/AWESOME_LIST_SUBMISSIONS.md`, which still markets the frozen CI product.

## 6. Smithery — smithery.ai

Smithery publishes local stdio servers as MCPB bundles.

```bash
cd mcp-server
npx @anthropic-ai/mcpb@2.1.2 pack . /tmp/getsonar-mcp-0.2.0.mcpb
```

1. Sign in at https://smithery.ai with GitHub (`Ivanolegvak`).
2. Publish the bundle: **Publish server** → *Local (MCPB bundle)* → upload `/tmp/getsonar-mcp-0.2.0.mcpb`,
   or `npx @smithery/cli mcp publish /tmp/getsonar-mcp-0.2.0.mcpb -n ivanolegvak/sonar`.
3. Name `ivanolegvak/sonar`, display name "SONAR: KYB due diligence", homepage
   `https://getsonar.report/integrations`, repository the public mirror.
4. Settings → Verification: complete the official-vendor checklist.

The same `.mcpb` file can be attached to the GitHub release of the mirror for one-click Claude
Desktop install.

## 7. mcp.so — https://mcp.so/submit

An older submission exists (CI-era copy). Sign in with GitHub, submit (or edit the existing entry):

- Name: `SONAR KYB` · URL: `https://github.com/Ivanolegvak/getsonar-mcp`
- Description: "KYB due diligence on vendors, partners and resellers for AI agents: registries,
  sanctions, PEP, ICIJ Offshore Leaks, adverse media. `uvx getsonar-mcp`."
- Server config: the Claude Desktop JSON from README.md.

## 8. mcpservers.org — https://mcpservers.org/submit

Same name, URL and description as step 7; category *Finance* (or *Business*). Replaces the old entry.

## Copy rules for every listing

- KYB due diligence for vendors, partners and resellers. Never "AML provider", "KYC provider" or
  "compliance decision"; SONAR is a due-diligence aid.
- No competitive intelligence or strategic accounts (frozen products).
- API pricing: €0.40 per `/findings`, €2.00 per `/run`, your first API call is free (one
  call since 2026-10-24). Say "your first call is free", not a multi-call or never-expiring
  allowance, and don't mix it up with the web app's free plan (2 reports a month).
- 13 national business registries (no Switzerland/Zefix).
