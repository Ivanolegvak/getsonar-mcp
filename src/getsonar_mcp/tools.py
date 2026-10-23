"""MCP tool definitions — shared across stdio and HTTP transports.

Each ``@mcp.tool`` calls the SONAR public API via ``client.call_sonar()``
and formats the response as Markdown the LLM can ingest. Tool annotations
follow the MCP spec (``readOnlyHint``, ``destructiveHint``, ``openWorldHint``)
so MCP clients can render them with appropriate UX warnings.

Tool catalogue (``TOOL_NAMES`` below is the single list; the smoke test,
README, server manifests and the /developers page are checked against it):

  - kyb_findings        — quick KYB lookup (structured findings, no AI summary)
  - kyb_run_submit      — full KYB report (AI-written summary, async)
  - adverse_media       — focused negative-media + complaints check
  - check_report_status — poll an async submission
  - account_balance     — read current balance + free trial calls remaining

v0.2.0 (SONAR relaunch T1.2): the competitive_findings /
competitive_run_submit tools were removed. Competitive Intelligence is
frozen and its /v1 agent answers 404 (SONAR_DECISIONS/ci_sa_freeze.md).
"""

from __future__ import annotations

import json
from typing import Any

from . import __version__
from .client import (
    KEYS_URL,
    call_sonar,
    format_findings,
    format_run_started,
    format_run_status,
    get_api_key_from_env,
)

SERVER_NAME = "SONAR KYB"

# Sent to the client at initialize time; most clients pass it to the model.
SERVER_INSTRUCTIONS = (
    "SONAR runs KYB (Know Your Business) due diligence on vendors, partners "
    "and resellers from public records: national business registries, "
    "sanctions and PEP lists, ICIJ Offshore Leaks and 10 years of adverse "
    "media, with a source link for every finding. It is a due-diligence "
    "aid, not a regulated AML/KYC provider: present results as findings "
    "for a human to review, never as a compliance decision. Always pass the "
    "company website when you know it (it disambiguates common names). "
    "Use kyb_findings for fast structured data, kyb_run_submit + "
    "check_report_status for the full written report, account_balance "
    "before a batch of calls. Paid calls: /findings EUR 0.40, /run EUR 2.00; "
    "every new account gets 3 free trial API calls."
)

TOOL_NAMES = (
    "kyb_findings",
    "kyb_run_submit",
    "adverse_media",
    "check_report_status",
    "account_balance",
)

# Cheapest paid call (/findings) and a full report (/run), in euro cents.
_FINDINGS_CENTS = 40
_RUN_CENTS = 200


def _euros(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}€{cents // 100}.{cents % 100:02d}"


def register_tools(mcp: Any) -> None:
    """Register all SONAR tools onto a FastMCP instance.

    Caller passes their FastMCP instance (different transports build the
    instance differently — see __main__.py and http_server.py).
    """
    # FastMCP (mcp 1.x) reports the *mcp library* version as serverInfo
    # unless told otherwise; directories and clients show that number.
    low_level = getattr(mcp, "_mcp_server", None)
    if low_level is not None:
        low_level.version = __version__

    # ── KYB ────────────────────────────────────────────────────────────────
    @mcp.tool(
        annotations={
            "title": "KYB Quick Lookup",
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        }
    )
    async def kyb_findings(company_name: str, website: str = "") -> str:
        """Run a fast KYB (Know Your Business) check on a company.

        Returns structured findings with source links: registry record
        (legal name, number, status, address, officers), sanctions and PEP
        matches, ICIJ Offshore Leaks hits, regulatory registers (e.g. FCA
        for UK firms) and adverse media. Synchronous, 30-90s, no AI-written
        summary. EUR 0.40 per call after the 3 free trial API calls.

        Args:
            company_name: Legal name of the company (e.g. "Tesco PLC")
            website: Company website URL, strongly recommended for disambiguation
        """
        api_key = get_api_key_from_env()
        body = {"company_name": company_name}
        if website:
            body["website"] = website
        result = await call_sonar(
            "POST",
            "/v1/agents/kyb-diligence/findings",
            api_key,
            body=body,
        )
        return format_findings(result, f"KYB Quick Lookup: {company_name}")

    @mcp.tool(
        annotations={
            "title": "KYB Full Report (async)",
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        }
    )
    async def kyb_run_submit(company_name: str, website: str = "") -> str:
        """Submit a full KYB due-diligence report (async).

        Returns a run_id immediately. Poll with check_report_status after
        1-3 minutes. The report has everything kyb_findings returns plus a
        PASS / REVIEW / FLAG verdict per check, risk flags, a written
        summary and recommended next steps for a human reviewer.
        EUR 2.00 per call after the 3 free trial API calls.

        Args:
            company_name: Legal name of the company
            website: Company website URL, strongly recommended
        """
        api_key = get_api_key_from_env()
        body = {"company_name": company_name}
        if website:
            body["website"] = website
        result = await call_sonar(
            "POST",
            "/v1/agents/kyb-diligence/run",
            api_key,
            body=body,
        )
        return format_run_started(result, "kyb-diligence")

    # ── Adverse Media ──────────────────────────────────────────────────────
    @mcp.tool(
        annotations={
            "title": "Adverse Media Check",
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        }
    )
    async def adverse_media(company_name: str, website: str = "") -> str:
        """Screen a company for negative news, complaints and bad reviews.

        Checks news sources (Google News + adverse-media search, 10-year
        lookback), BBB, Clutch.co, Yelp, App Store, Facebook and Reddit.
        No sanctions/PEP screening: use kyb_findings for that.
        EUR 0.40 per call after the 3 free trial API calls.

        Args:
            company_name: Company to screen
            website: Company website URL for accuracy
        """
        api_key = get_api_key_from_env()
        body = {"company_name": company_name}
        if website:
            body["website"] = website
        result = await call_sonar(
            "POST",
            "/v1/agents/adverse-media/findings",
            api_key,
            body=body,
        )
        return format_findings(result, f"Adverse Media: {company_name}")

    # ── Async polling ──────────────────────────────────────────────────────
    @mcp.tool(
        annotations={
            "title": "Check Report Status",
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        }
    )
    async def check_report_status(
        run_id: str,
        agent_type: str = "kyb-diligence",
    ) -> str:
        """Poll the status of an async report submitted via kyb_run_submit.

        Returns a compact summary of the report when status='completed'.
        Reports typically complete in 60-180s. Free (no charge).

        Args:
            run_id: The run_id returned by kyb_run_submit
            agent_type: One of "kyb-diligence", "adverse-media"
        """
        valid = {"kyb-diligence", "adverse-media"}
        if agent_type not in valid:
            return json.dumps(
                {"error": f"Invalid agent_type. Must be one of: {sorted(valid)}"}
            )
        api_key = get_api_key_from_env()
        result = await call_sonar(
            "GET",
            f"/v1/agents/{agent_type}/run/{run_id}",
            api_key,
        )
        return format_run_status(result)

    # ── Account / billing ──────────────────────────────────────────────────
    @mcp.tool(
        annotations={
            "title": "Account Balance & Usage",
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        }
    )
    async def account_balance() -> str:
        """Check API usage, free trial calls remaining and pre-paid balance.

        Useful for AI agents to decide whether the next call will be free,
        paid, or fail with insufficient balance. Every new account gets 3
        free trial API calls (any endpoint, granted once at signup, not
        monthly). After that, /findings calls deduct EUR 0.40 and /run calls
        deduct EUR 2.00 from the balance. Free (no charge).
        """
        api_key = get_api_key_from_env()
        result = await call_sonar("GET", "/v1/usage", api_key)
        if result.get("error"):
            return f"⚠️  Couldn't read account: {result.get('message', '')}"
        period = result.get("period", "")
        total = result.get("total_requests", 0)
        free_remaining = result.get("free_trial_remaining", 0)
        balance_cents = result.get("balance_cents", 0)
        by_endpoint = result.get("by_endpoint", {}) or {}
        lines = [
            f"# Account usage — {period}",
            f"- Calls this month: **{total}**",
            f"- Free trial calls remaining: **{free_remaining}** (granted once at signup)",
            f"- Pre-paid balance: **{_euros(balance_cents)}**",
        ]
        if by_endpoint:
            lines.append("")
            lines.append("By endpoint:")
            for k, v in sorted(by_endpoint.items()):
                lines.append(f"  - {k}: {v}")
        if free_remaining == 0 and balance_cents < _FINDINGS_CENTS:
            lines.append("")
            lines.append(
                f"⚠️  Free trial used up and balance is below {_euros(_FINDINGS_CENTS)} "
                f"(the cheapest /findings call). Top up at {KEYS_URL}."
            )
        elif free_remaining == 0 and balance_cents < _RUN_CENTS:
            lines.append("")
            lines.append(
                "ℹ️  Free trial used up. Balance covers /findings calls but not "
                f"/run reports ({_euros(_RUN_CENTS)} each). Top up at {KEYS_URL}."
            )
        return "\n".join(lines)
