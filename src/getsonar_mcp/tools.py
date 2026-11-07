"""MCP tool definitions — shared across stdio and HTTP transports.

Each ``@mcp.tool`` calls the SONAR public API via ``client.call_sonar()``
and formats the response as Markdown the LLM can ingest. Tool annotations
follow the MCP spec (``readOnlyHint``, ``destructiveHint``, ``openWorldHint``)
so MCP clients can render them with appropriate UX warnings.

Tool catalogue (``TOOL_NAMES`` below is the single list; the smoke test,
README, server manifests and the /developers page are checked against it):

  - company_lookup      : register check (exists / active / good standing), €0.01 if found
  - company_officers    : a company's officers from its register, €0.01 if found
  - kyb_findings        : KYB screening (register, owners, sanctions, PEP,
                          offshore records, adverse media), no AI summary, €0.50
  - kyb_run_submit      : full KYB report (AI-written summary, async), €6.00
  - adverse_media       : focused negative-media + complaints check, €0.50
  - check_report_status : poll an async submission, free
  - account_balance     : balance, free trial call and free lookups left, free

v0.2.0 (SONAR relaunch T1.2): the competitive_findings /
competitive_run_submit tools were removed. Competitive Intelligence is
frozen and its /v1 agent answers 404 (SONAR_DECISIONS/ci_sa_freeze.md).
v0.3.0 (2026-11-07): company_lookup and company_officers
(``/v1/companies``); kyb_findings / kyb_run_submit take the KYB
identifiers (country, state, registration_number, vat_number).
"""

from __future__ import annotations

import json
from typing import Any, Literal, Optional
from urllib.parse import quote

from . import __version__
from .client import (
    KEYS_URL,
    call_findings,
    call_sonar,
    format_findings,
    format_lookup,
    format_officers,
    format_run_started,
    format_run_status,
    get_api_key_from_env,
)

SERVER_NAME = "SONAR KYB"

# Sent to the client at initialize time; most clients pass it to the model.
SERVER_INSTRUCTIONS = (
    "SONAR runs KYB (Know Your Business) due diligence on vendors, partners "
    "and resellers from public records: national company registers, "
    "sanctions and PEP lists, offshore-leak records and 10 years of adverse "
    "media. It is a due-diligence aid, not a regulated AML/KYC provider: "
    "present results as findings for a human to review, never as a "
    "compliance decision. Pick the cheapest tool that answers the question: "
    "company_lookup (EUR 0.01, only when the company is found; the first 100 "
    "found are free) for 'does this company exist / is it registered / is it "
    "active or in good standing'; company_officers (same price) for its "
    "directors; kyb_findings (EUR 0.50) for sanctions, PEP, offshore-leak, "
    "ownership and adverse-media screening; kyb_run_submit (EUR 6.00) only "
    "when the user asks for a full written KYB report. Always pass the "
    "country (ISO code) and, when known, the registration number and "
    "website: without a country no register is searched. Call "
    "account_balance before a batch of paid calls. A new account's first "
    "findings or report call is free."
)

TOOL_NAMES = (
    "company_lookup",
    "company_officers",
    "kyb_findings",
    "kyb_run_submit",
    "adverse_media",
    "check_report_status",
    "account_balance",
)

# Cheapest paid call (/findings) and a full report (/run), in euro cents.
_FINDINGS_CENTS = 50
_RUN_CENTS = 600


def _euros(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}€{cents // 100}.{cents % 100:02d}"


def _agent_body(
    company_name: str,
    website: str,
    country: str,
    registration_number: str,
    state: str,
    vat_number: str,
) -> dict[str, str]:
    """The /v1/agents request body: only the fields that were given
    (``AgentIdentifiers`` in the API rejects empty strings)."""
    body = {"company_name": company_name}
    for key, value in (
        ("website", website.strip()),
        ("country", country.strip().upper()),
        ("registration_number", registration_number.strip()),
        ("state", state.strip().upper()),
        ("vat_number", vat_number.strip().replace(" ", "").upper()),
    ):
        if value:
            body[key] = value
    return body


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

    # ── Company register (/v1/companies) ───────────────────────────────────
    @mcp.tool(
        annotations={
            "title": "Company Register Lookup",
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        }
    )
    async def company_lookup(
        country: str,
        company_name: str = "",
        registration_number: str = "",
        state: str = "",
        include: Optional[list[Literal["officers", "filings"]]] = None,
    ) -> str:
        """Check a national company register: does this company exist, is it
        registered, is it active, is it in good standing?

        Use this first for any "is X a real / registered / active company"
        question; it is the cheapest call. One live search of the official
        register, about a second. Returns FOUND / NOT_FOUND / AMBIGUOUS with
        the full register record: legal name, number, status (active /
        inactive), good_standing (overdue filings, strike-off, insolvency),
        legal form, incorporation date, address, VAT number, previous names,
        US registered agent. The name must match exactly (case, punctuation
        and legal-form spelling aside); a look-alike name is NOT_FOUND.
        No sanctions, PEP or adverse-media screening: use kyb_findings.

        Price: EUR 0.01 only when the company is found (the first 100 found
        lookups per account are free); NOT_FOUND costs nothing.

        Countries: GB, FR, CZ, SK, NO, FI, CH, EE, LV, US (by name or number);
        PL, BE, BR by registration_number only. US needs `state` (NY, CO, OR,
        CT, TX, PA, FL).

        Args:
            country: ISO 3166-1 alpha-2 code of the register, e.g. "GB"
            company_name: Exact legal name, e.g. "Tesco PLC". Optional when
                registration_number is given
            registration_number: The register's number (GB company number,
                FR SIREN, CZ / SK ICO, NO orgnr, PL KRS, ...). Matched
                exactly; decides alone when given. Prefer it when known
            state: US only (required there): 2-letter state code
            include: Also return the found company's "officers" (GB, CZ, SK,
                NO, FR) and / or latest "filings" (GB, FR), at no extra cost
        """
        if not company_name.strip() and not registration_number.strip():
            return "⚠️  Give company_name or registration_number."
        api_key = get_api_key_from_env()
        body: dict[str, Any] = {"country": country.strip().upper()}
        if company_name.strip():
            body["company_name"] = company_name.strip()
        if registration_number.strip():
            body["registration_number"] = registration_number.strip()
        if state.strip():
            body["state"] = state.strip().upper()
        if include:
            body["include"] = list(dict.fromkeys(include))
        result = await call_sonar("POST", "/v1/companies/lookup", api_key, body=body)
        return format_lookup(result)

    @mcp.tool(
        annotations={
            "title": "Company Officers",
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        }
    )
    async def company_officers(country: str, registration_number: str) -> str:
        """List a company's officers (directors, secretaries, board members)
        from its national register, current and former, with appointment and
        resignation dates where the register publishes them.

        Needs the registration number (get it from company_lookup). For
        officers together with the register check, call company_lookup with
        include=["officers"] instead: one call, one price.

        Price: EUR 0.01 only when the register holds the company (free
        lookups first); NOT_FOUND costs nothing.
        Countries: GB, CZ, SK, NO, FR (GB, CZ, SK also list former officers).

        Args:
            country: ISO 3166-1 alpha-2 code, e.g. "GB"
            registration_number: The register's company number, e.g. "00445790"
        """
        api_key = get_api_key_from_env()
        cc = country.strip().upper()
        number = quote(registration_number.strip(), safe="")
        result = await call_sonar(
            "GET", f"/v1/companies/{quote(cc, safe='')}/{number}/officers", api_key
        )
        return format_officers(result)

    # ── KYB agent ──────────────────────────────────────────────────────────
    @mcp.tool(
        annotations={
            "title": "KYB Screening (findings)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        }
    )
    async def kyb_findings(
        company_name: str,
        website: str = "",
        country: str = "",
        registration_number: str = "",
        state: str = "",
        vat_number: str = "",
    ) -> str:
        """Screen a company for KYB risk: sanctions and PEP matches,
        offshore-leak records, regulatory records, beneficial owners and
        adverse media, plus the company register's answer (registry_match,
        good standing). Structured findings, each naming the kind of source;
        no AI-written summary.

        Use this for "screen / vet / check X for sanctions, PEP or bad
        press". For only "does it exist / is it active", company_lookup is
        far cheaper. Usually 30-90 s (the tool waits for queued results).

        Price: EUR 0.50 per call, charged even when nothing is found (a new
        account's first call is free). Rate limit: 10 calls a minute per key.

        Args:
            company_name: Legal name of the company (e.g. "Tesco PLC")
            website: Company website URL (http/https), strongly recommended:
                it separates the company from others with a similar name
            country: ISO 3166-1 alpha-2 country of registration. Without it
                no company register is searched (registry_match NOT_SEARCHED)
            registration_number: The register's company number; needs country
            state: US only: 2-letter state of formation
            vat_number: VAT number with its country prefix, e.g. "DE123456789"
        """
        api_key = get_api_key_from_env()
        body = _agent_body(
            company_name, website, country, registration_number, state, vat_number
        )
        result = await call_findings("/v1/agents/kyb-diligence/findings", api_key, body)
        return format_findings(result, f"KYB Screening: {company_name}")

    @mcp.tool(
        annotations={
            "title": "KYB Full Report (async, EUR 6)",
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": True,
        }
    )
    async def kyb_run_submit(
        company_name: str,
        website: str = "",
        country: str = "",
        registration_number: str = "",
        state: str = "",
        vat_number: str = "",
    ) -> str:
        """Order a full written KYB due-diligence report (async). Use ONLY
        when the user asks for a full or written report: it costs EUR 6.00
        per call (a new account's first call is free). For a quick check use
        company_lookup (EUR 0.01) or kyb_findings (EUR 0.50).

        Returns a run_id immediately; poll check_report_status after 1-3
        minutes. The report has everything kyb_findings returns plus a
        PASS / REVIEW / FLAG verdict per check, risk flags, a written
        summary and next steps for a human reviewer.

        Args:
            company_name: Legal name of the company
            website: Company website URL, strongly recommended
            country: ISO 3166-1 alpha-2 country of registration; without it
                no company register is searched
            registration_number: The register's company number; needs country
            state: US only: 2-letter state of formation
            vat_number: VAT number with its country prefix
        """
        api_key = get_api_key_from_env()
        body = _agent_body(
            company_name, website, country, registration_number, state, vat_number
        )
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
        """Screen a company for negative news, complaints and bad reviews
        only (10-year news lookback, complaint and review sites).

        No register, sanctions or PEP screening: kyb_findings covers those
        and adverse media at the same price, so prefer it unless the user
        wants news and reviews only.
        Price: EUR 0.50 per call (a new account's first call is free).

        Args:
            company_name: Company to screen
            website: Company website URL for accuracy
        """
        api_key = get_api_key_from_env()
        body = {"company_name": company_name}
        if website:
            body["website"] = website
        result = await call_findings("/v1/agents/adverse-media/findings", api_key, body)
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
        Reports usually complete in about 2 minutes, up to about 4. Free (no charge).

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
            f"/v1/agents/{agent_type}/run/{quote(run_id.strip(), safe='')}",
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
        """Check the prepaid balance, the free trial call and the free
        company lookups left, and this month's calls. Free (no charge).

        Call it before a batch of paid calls to know whether they will be
        free, paid or refused (402). Prices: company_lookup and
        company_officers EUR 0.01 when found (100 free per account),
        kyb_findings / adverse_media EUR 0.50, kyb_run_submit EUR 6.00. A new
        account's first findings or report call is free.
        """
        api_key = get_api_key_from_env()
        result = await call_sonar("GET", "/v1/usage", api_key)
        if result.get("error") is True:
            return f"⚠️  Couldn't read account: {result.get('message', '')}"
        period = result.get("period", "")
        total = result.get("total_requests", 0)
        free_remaining = result.get("free_trial_remaining", 0)
        balance_cents = result.get("balance_cents", 0)
        free_lookups = result.get("free_lookups_remaining")
        by_endpoint = result.get("by_endpoint", {}) or {}
        lines = [
            f"# Account usage: {period}",
            f"- Calls this month: **{total}**",
            f"- Free trial calls remaining: **{free_remaining}** (granted once at signup)",
            f"- Pre-paid balance: **{_euros(balance_cents)}**",
        ]
        if isinstance(free_lookups, int):
            lines.append(
                f"- Free company lookups remaining: **{free_lookups}** "
                "(spent only when a lookup finds the company)"
            )
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
