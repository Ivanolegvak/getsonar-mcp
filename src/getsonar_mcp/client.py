"""HTTP client + response formatters for the SONAR public API.

Shared by both stdio and streamable-http MCP transports. The transport
layer just wires up tool dispatch; this module owns the actual API calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger("getsonar-mcp.client")

# Public-API base URL. Custom-domain default — overridable for staging /
# self-hosted deployments via env.
DEFAULT_API_BASE = "https://api.getsonar.report"

DEFAULT_TIMEOUT_S = 120
# Server-side bounded wait we ask /findings for: stays under the HTTP timeout.
FINDINGS_SERVER_WAIT_S = 90

# Where customers create API keys and top up their balance.
KEYS_URL = "https://getsonar.report/developer/keys"


def get_api_base() -> str:
    return os.environ.get("SONAR_API_BASE", DEFAULT_API_BASE).rstrip("/")


def get_default_timeout() -> int:
    raw = os.environ.get("SONAR_API_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        return max(5, int(raw))
    except ValueError:
        return DEFAULT_TIMEOUT_S


def get_api_key_from_env() -> str:
    """Resolve the API key from the environment. Raises a friendly error
    when the env var is missing — the most common config mistake."""
    key = os.environ.get("SONAR_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "SONAR_API_KEY environment variable is not set. "
            f"Get a key at {KEYS_URL}, then add "
            "SONAR_API_KEY to your MCP client config."
        )
    return key


async def call_sonar(
    method: str,
    path: str,
    api_key: str,
    *,
    body: Optional[dict] = None,
    timeout: Optional[int] = None,
) -> dict:
    """Call the SONAR REST API and return the parsed JSON response.

    Returns ``{"error": True, "status": int, "message": str}`` on non-200
    so callers can format a friendly message without try/except.
    """
    # Pull version dynamically so the User-Agent stays in sync with
    # whatever pyproject.toml + __init__.py advertise. Avoids the
    # stale "0.1.0" string we shipped on early versions.
    from . import __version__ as _mcp_version

    url = f"{get_api_base()}{path}"
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
        "User-Agent": f"getsonar-mcp/{_mcp_version}",
    }
    actual_timeout = timeout or get_default_timeout()

    try:
        async with httpx.AsyncClient(timeout=actual_timeout) as c:
            if method == "POST":
                resp = await c.post(url, json=body or {}, headers=headers)
            else:
                resp = await c.get(url, headers=headers)
    except httpx.TimeoutException:
        return {
            "error": True,
            "status": 0,
            "message": (
                f"Request to {path} timed out after {actual_timeout}s. "
                "The /findings endpoint answers within ~90s (findings, or "
                "202 with a poll URL); if you're consistently timing out, "
                "raise SONAR_API_TIMEOUT."
            ),
        }
    except httpx.RequestError as e:
        return {
            "error": True,
            "status": 0,
            "message": f"Network error calling {path}: {type(e).__name__}",
        }

    if resp.status_code != 200 and resp.status_code != 202:
        return {
            "error": True,
            "status": resp.status_code,
            "message": _error_message(resp)[:600],
        }

    try:
        return resp.json()
    except ValueError:
        return {
            "error": True,
            "status": resp.status_code,
            "message": "non-JSON response",
        }


def _error_message(resp: httpx.Response) -> str:
    """One line for the model from a SONAR error body.

    The public API wraps errors as ``{"detail": {"error": {"code",
    "message", "reason"?, "supported_states"?}}}``; request validation
    (422) answers ``{"detail": [{"loc", "msg"}, ...]}``. The code and
    reason are kept: they tell the model what to change (e.g.
    NAME_SEARCH_NOT_SUPPORTED: send registration_number).
    """
    try:
        body = resp.json()
    except ValueError:
        return resp.text
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        err = detail["error"]
        head = " ".join(str(err[k]) for k in ("code", "reason") if err.get(k))
        msg = str(err.get("message") or "")
        if err.get("supported_states"):
            msg += f" Supported states: {', '.join(map(str, err['supported_states']))}."
        return f"{head}: {msg}" if head else msg
    if isinstance(detail, list):
        parts = []
        for d in detail:
            if isinstance(d, dict):
                loc = ".".join(str(x) for x in (d.get("loc") or [])[1:])
                parts.append(
                    f"{loc}: {d.get('msg', '')}" if loc else str(d.get("msg", ""))
                )
        return "Invalid input. " + "; ".join(parts)
    if detail:
        return str(detail)
    return resp.text


# Total time kyb_findings keeps polling a queued /findings job (the API
# answers 202 + poll_url when the collection outlasts its bounded wait).
FINDINGS_POLL_BUDGET_S = 300
FINDINGS_POLL_MIN_S = 2


async def call_findings(path: str, api_key: str, body: dict) -> dict:
    """POST a /findings call and, on 202, poll its ``poll_url`` until the
    findings are ready (200), the job fails, or the poll budget runs out.

    The API runs the collectors on its queue worker: the POST waits up to
    ``?wait=`` seconds server-side (we ask for :data:`FINDINGS_SERVER_WAIT_S`,
    under our HTTP timeout), then answers 202 ``{job_id, status, poll_url}``
    with ``Retry-After``. Older API versions answered 200 directly (and
    ignore ``wait``); that path is unchanged.
    """
    wait = max(0, min(FINDINGS_SERVER_WAIT_S, get_default_timeout() - 15))
    sep = "&" if "?" in path else "?"
    result = await call_sonar("POST", f"{path}{sep}wait={wait}", api_key, body=body)
    deadline = time.monotonic() + FINDINGS_POLL_BUDGET_S
    while (
        result.get("error") is not True
        and result.get("poll_url")
        and result.get("status") in ("pending", "running")
    ):
        if time.monotonic() >= deadline:
            return {
                "error": True,
                "status": 202,
                "message": (
                    f"Findings are still being collected (job {result.get('job_id')}). "
                    f"Fetch them later with GET {result['poll_url']}."
                ),
            }
        delay = max(FINDINGS_POLL_MIN_S, int(result.get("retry_after_seconds") or 5))
        await asyncio.sleep(delay)
        result = await call_sonar("GET", result["poll_url"], api_key)
    return result


# ── Response formatters ──────────────────────────────────────────────────────


def format_findings(result: dict, title: str) -> str:
    """Format a /findings API response as readable Markdown for the LLM.

    Phase AD3 follow-up (2026-05-09) — Bug 9 fix:
      Added (a) field_status 3-state surfacing (Bug 5), and
      (b) a hard 22 KB output cap to stay safely under MCP's
      ~25 KB transport boundary even for big reports.
    """
    if result.get("error") is True:
        return _format_error(result, "SONAR API error")

    fields = result.get("fields", {}) or {}
    found = result.get("fields_found", []) or []
    not_found = result.get("fields_not_found", []) or []
    field_status = result.get("field_status", {}) or {}
    sources = result.get("sources_checked", 0)
    time_ms = result.get("processing_time_ms", 0)

    parts = [
        f"# {title}",
        f"Sources checked: {sources} · Processing time: {time_ms}ms",
    ]
    if result.get("request_id"):
        parts.append(f"Request ID: `{result['request_id']}`")

    # Register answer first: it says whether the company exists at all,
    # which is how every other field should be read.
    registry = result.get("registry_match")
    if isinstance(registry, dict):
        parts.append("")
        parts.append(format_registry_match(registry))

    # Phase AD3: the per-field status (found / checked_clean / not_run /
    # company_not_found). Falls back to the legacy fields_found /
    # fields_not_found split if the backend does not send it.
    if field_status:

        def _with(status: str) -> list[str]:
            return sorted(k for k, v in field_status.items() if v == status)

        parts.append("")
        if found:
            parts.append(f"**Found data**: {', '.join(found)}")
        if _with("checked_clean"):
            parts.append(
                "**Checked, clean** (the check ran and returned nothing about the "
                f"company): {', '.join(_with('checked_clean'))}"
            )
        if _with("company_not_found"):
            parts.append(
                "**Company not in the register** (the register answered and holds no "
                f"such company): {', '.join(_with('company_not_found'))}"
            )
        if _with("not_run"):
            parts.append(
                "**Not run** (no information, never read as clean): "
                f"{', '.join(_with('not_run'))}"
            )
    else:
        parts.append(f"Fields with data: {', '.join(found) if found else 'none'}")
        if not_found:
            parts.append(f"No data for: {', '.join(not_found)}")
    parts.append("")

    ubo = result.get("ubo_graph")
    if isinstance(ubo, dict):
        ubo_text = format_ubo_graph(ubo)
        if ubo_text:
            parts.append(ubo_text)
            parts.append("")

    for field_name, field_data in fields.items():
        findings = (field_data or {}).get("findings", []) or []
        confidence = (field_data or {}).get("confidence") or "N/A"
        if findings:
            label = field_name.replace("_", " ").title()
            parts.append(f"## {label} (confidence: {confidence})")
            for f in findings:
                value = f.get("value", "") or ""
                detail = f.get("detail", "") or ""
                parts.append(f"- **{value}**")
                if detail:
                    parts.append(f"  {detail}")
                # 2026-11-06: ``provider`` names the kind of source
                # (company_register, sanctions_lists, news_search, ...); links to
                # registers and aggregators are dropped, news links stay.
                refs = []
                for s in (f.get("sources") or [])[:3]:
                    kind = (s or {}).get("provider") or ""
                    url = (s or {}).get("url") or ""
                    ref = " ".join(x for x in (kind, url) if x)
                    if ref and ref not in refs:
                        refs.append(ref)
                if refs:
                    parts.append(f"  Source: {'; '.join(refs)}")
                if f.get("source_date"):
                    parts.append(f"  Dated: {f['source_date']}")
            parts.append("")

    if not found:
        parts.append(
            "No findings in any field. Read the statuses above: only "
            "'Checked, clean' fields are a clean result."
        )

    return _cap(
        "\n".join(parts),
        "Fetch the full JSON via the REST API: POST /v1/agents/<agent>/findings "
        "(or GET /v1/agents/findings/<job_id>).",
    )


# Under MCP's ~25 KB transport boundary, with room for the footer.
_MAX_CHARS = 22000


def _cap(out: str, how_to_get_all: str) -> str:
    """Truncate at a paragraph break (better than a mid-string clip)."""
    if len(out) <= _MAX_CHARS:
        return out
    cut = out[:_MAX_CHARS].rsplit("\n\n", 1)[0]
    return (
        cut
        + f"\n\n---\n_(response truncated to fit the MCP transport. {how_to_get_all})_"
    )


def _format_error(result: dict, what: str) -> str:
    status = result.get("status", "?")
    msg = result.get("message", "unknown error")
    if status == 402:
        # Verbatim: it carries the top-up URL the customer needs to see.
        return f"⚠️  Insufficient balance.\n\n{msg}"
    if status == 403 and "SANDBOX_KEY" in str(msg):
        return (
            f"⚠️  {what} (HTTP 403).\n\n{msg}\n\nA test key (sk-sonar-test-) only "
            "runs company_lookup, company_officers and account_balance."
        )
    return f"⚠️  {what} (HTTP {status}).\n\n{msg}"


def _good_standing(v: object) -> str:
    if v is True:
        return "yes (active, no default or insolvency marker on the register)"
    if v is False:
        return "NO (closed, or the register marks a default or insolvency)"
    return "not published by this register"


def format_registry_match(rm: dict) -> str:
    """The ``registry_match`` block of a /findings answer (2026-11-06)."""
    status = rm.get("status") or "?"
    where = rm.get("country") or ""
    if rm.get("state"):
        where += f"-{rm['state']}"
    lines = [f"## Company register: **{status}**" + (f" ({where})" if where else "")]
    if status == "NOT_SEARCHED":
        lines.append(
            f"No register answer (reason: {rm.get('reason') or 'unknown'}). Never read "
            "this as clean. Pass `country` (and `state` for the US) to search the register."
        )
    elif status == "NOT_FOUND":
        lines.append(
            "The register answered and holds no company of this exact name or number."
        )
    elif status == "AMBIGUOUS":
        lines.append(
            "More than one active company holds this name: pass `registration_number`."
        )
    for key, label in (
        ("name", "Registered name"),
        ("registration_number", "Number"),
        ("company_status", "Status"),
        ("legal_form", "Legal form"),
        ("incorporated_on", "Incorporated"),
        ("address", "Address"),
        ("vat_id", "VAT"),
        ("jurisdiction", "Jurisdiction"),
    ):
        if rm.get(key):
            lines.append(f"- {label}: {rm[key]}")
    if status == "FOUND":
        lines.append(f"- Good standing: {_good_standing(rm.get('good_standing'))}")
    if rm.get("previous_names"):
        lines.append(f"- Previous names: {', '.join(rm['previous_names'])}")
    agent = rm.get("registered_agent")
    if isinstance(agent, dict) and agent.get("name"):
        lines.append(
            f"- Registered agent: {agent['name']}"
            + (f", {agent['address']}" if agent.get("address") else "")
        )
    for m in (rm.get("matches") or [])[:10]:
        if status != "FOUND" or len(rm.get("matches") or []) > 1:
            lines.append(
                f"- Candidate: {m.get('name')} ({m.get('registration_number') or 'no number'}), "
                f"{m.get('status') or 'unknown'}"
            )
    if rm.get("last_updated"):
        lines.append(f"- Register read: {rm['last_updated']}")
    return "\n".join(lines)


def format_ubo_graph(g: dict) -> str:
    """Ultimate beneficial owners from ``ubo_graph`` (one line each)."""
    ubos = g.get("ubos") or []
    gaps = g.get("gaps") or []
    if not ubos and not gaps and g.get("status") in (None, "not_run"):
        return ""
    lines = [f"## Beneficial owners (ownership chain: {g.get('status') or 'unknown'})"]
    for u in ubos[:10]:
        share = u.get("effective_text") or (
            "by control" if u.get("basis") == "control" else "share not published"
        )
        via = f", {u['via']}" if u.get("via") else ""
        conf = "" if u.get("confirmed") else " (possible, unconfirmed)"
        lines.append(f"- {u.get('name')}: {share}{via}{conf}")
    if not ubos:
        lines.append("- No beneficial owner identified.")
    for x in gaps[:5]:
        lines.append(f"- Gap: {x.get('text') or x.get('name')}")
    return "\n".join(lines)


def _json_block(result: dict) -> str:
    return "```json\n" + json.dumps(result, indent=1, ensure_ascii=False) + "\n```"


def _price_line(result: dict) -> str:
    cents = result.get("price_cents")
    if result.get("sandbox"):
        price = "free (test key)"
    elif isinstance(cents, int):
        price = "free" if cents == 0 else f"€{cents // 100}.{cents % 100:02d}"
    else:
        price = "unknown"
    left = result.get("free_lookups_remaining")
    return f"Charged: {price}" + (
        f" · Free lookups left: {left}" if isinstance(left, int) else ""
    )


def format_lookup(result: dict) -> str:
    """A ``POST /v1/companies/lookup`` answer: a short headline the model
    can act on, then the full JSON (every field, nothing dropped)."""
    if result.get("error") is True:
        return _format_error(result, "Company lookup failed")
    q = result.get("query") or {}
    subject = q.get("company_name") or q.get("registration_number") or "?"
    where = (q.get("country") or "") + (f"-{q['state']}" if q.get("state") else "")
    status = result.get("status") or "?"
    matches = result.get("matches") or []
    lines = [f"# Company lookup: {subject} ({where}): **{status}**"]
    if status == "FOUND" and matches:
        m = matches[0]
        lines.append(
            f"- {m.get('name')} ({m.get('registration_number')}): {m.get('status')}"
            + (
                f" (register: {m['register_status']})"
                if m.get("register_status")
                else ""
            )
        )
        lines.append(f"- Good standing: {_good_standing(m.get('good_standing'))}")
    elif status == "NOT_FOUND":
        lines.append(
            "- The register holds no company of exactly this name (or number). A name that "
            "only resembles a registered one is NOT_FOUND."
        )
    elif status == "AMBIGUOUS":
        lines.append(
            f"- {len(matches)} active companies hold this name: ask for or pass "
            "registration_number."
        )
    if result.get("truncated"):
        lines.append(
            "- truncated: the register holds more companies of this name than it returned; "
            "matches may be incomplete. Search by registration_number."
        )
    if result.get("coverage_note"):
        lines.append(f"- Coverage: {result['coverage_note']}")
    if result.get("sandbox"):
        lines.append("- Sandbox answer (test key): a fixed, made-up scenario.")
    lines.append(f"- {_price_line(result)}")
    lines.append("")
    lines.append("Full answer:")
    lines.append(_json_block(result))
    rid = result.get("request_id") or "<request_id>"
    return _cap(
        "\n".join(lines),
        f"GET /v1/companies/lookup/{rid} returns the full answer again, free.",
    )


def format_officers(result: dict) -> str:
    """A ``GET /v1/companies/{cc}/{no}/officers`` answer: headline + JSON."""
    if result.get("error") is True:
        return _format_error(result, "Officers lookup failed")
    q = result.get("query") or {}
    officers = result.get("officers") or []
    current = sum(1 for o in officers if o.get("current"))
    name = (result.get("company") or {}).get("name") or q.get("registration_number")
    lines = [
        f"# Officers: {name} ({q.get('country')} {q.get('registration_number')}): "
        f"**{result.get('status')}**",
        f"- {current} current, {len(officers) - current} former"
        + (
            ""
            if result.get("history") is not False
            else " (this register lists current officers only)"
        ),
        f"- {_price_line(result)}",
        "",
        "Full answer:",
        _json_block(result),
    ]
    return _cap(
        "\n".join(lines),
        "Call GET /v1/companies/{country}/{registration_number}/officers for the full list.",
    )


def format_run_started(result: dict, agent_type: str) -> str:
    """Format the /run async-submit response."""
    if result.get("error") is True:
        return _format_error(result, "Failed to start report")

    run_id = result.get("run_id", "")
    status = result.get("status", "")
    est = result.get("estimated_seconds", 90)
    return (
        f"Report submitted.\n"
        f"- Run ID: `{run_id}`\n"
        f"- Status: {status}\n"
        f"- Estimated time: {est} seconds\n\n"
        f"Call `check_report_status` with run_id='{run_id}' and "
        f"agent_type='{agent_type}' in 30-60 seconds to get the result."
    )


def format_run_status(result: dict) -> str:
    """Format the /run/{id} status-poll response.

    Phase AD3 follow-up (2026-05-09) — Bug 9 fix:
      Previously dumped the entire report JSON and sliced at 8000 chars,
      causing mid-string truncation Claude Desktop surfaced. Reports
      are 30-50 KB; slicing always cut a critical structured field.

      New approach: render a COMPACT NARRATIVE (~3-6 KB typical) that
      contains every customer-relevant signal without the JSON schema
      overhead. Fits comfortably under MCP's ~25 KB transport boundary.

      Customers who need the full structured report can fetch via
      direct API call to /v1/agents/<agent>/run/<run_id> — included
      as a footnote in the response.
    """
    # ``error is True`` is call_sonar's transport / HTTP error. A failed run
    # answers 200 with ``error`` = the failure message (a string), which
    # must reach the "Report failed" branch below, not this one.
    if result.get("error") is True:
        return _format_error(result, "Failed to check report status")

    status = result.get("status", "unknown")
    if status == "completed":
        return _format_completed_report(result)
    if status == "failed":
        err = result.get("error_message") or result.get("error") or "Unknown error"
        return f"Report failed: {err}"
    return f"Report status: {status}. Still processing, check again in 15-30 seconds."


def _format_completed_report(result: dict) -> str:
    """Compact narrative renderer for completed reports.

    Output sections:
      • Headline (status, risk level, screening, UBO, company status)
      • Run metadata (run_id, time, signals)
      • Company information (one-liner per field, skip empties)
      • Verification checks (compact table)
      • Risk flags (one bullet each)
      • Top director appointments (last 3)
      • Sanctions screening summary
      • Field availability (which collectors emitted data)
      • Footer with full-report URL
    """
    run_id = result.get("run_id") or "unknown"
    agent = result.get("agent") or "kyb-diligence"
    company = (result.get("company") or {}).get("name", "Subject")
    findings = result.get("result") or result.get("findings_json") or {}
    report = result.get("report") or result.get("report_json") or {}

    # Some endpoints return report inline; some return findings; we
    # need both shapes. Findings has fields[].findings; report has
    # report_content (the LLM-narrated structured doc).
    report_content = report.get("report_content")
    if isinstance(report_content, str):
        try:
            report_content = json.loads(report_content)
        except (json.JSONDecodeError, TypeError):
            report_content = {}
    elif not isinstance(report_content, dict):
        report_content = {}

    obs = report.get("observability") or {}
    sweep_s = obs.get("sweep_duration_seconds") or 0
    signals_used = obs.get("osint_signals_used") or 0
    cov = obs.get("sanctions_coverage") or {}

    sections: list[str] = []

    # ── Headline ──────────────────────────────────────────────────────
    overall = report_content.get("overall_status") or "—"
    risk = report_content.get("risk_level") or "—"
    # `aml_screening_result` is the backend field name for the sanctions /
    # PEP screening outcome. SONAR is not a regulated AML provider, so the
    # label says "Screening".
    screening = report_content.get("aml_screening_result") or "—"
    ubo = report_content.get("ubo_verified") or "—"
    company_status = report_content.get("company_status") or "—"

    sections.append(
        f"# {company} — KYB Report\n\n"
        f"**Overall: {overall}** · Risk: {risk} · Screening: {screening} · "
        f"UBO: {ubo} · Status: {company_status}"
    )

    # ── Run metadata ──────────────────────────────────────────────────
    # Cost intentionally omitted — operator preference. Customers using
    # SONAR through Claude shouldn't see per-report dollar figures.
    sections.append(f"**Run**: `{run_id}` · {int(sweep_s)}s · {signals_used} signals")

    # ── Company register (2026-11-06) ─────────────────────────────────
    registry = findings.get("registry_match") if isinstance(findings, dict) else None
    if isinstance(registry, dict):
        sections.append(format_registry_match(registry))

    # ── Company Information ───────────────────────────────────────────
    ci = report_content.get("company_information") or {}
    if ci:
        rows = []
        for key, label in [
            ("legal_name", "Legal name"),
            ("registration_number", "Reg No."),
            ("legal_form", "Form"),
            ("date_of_incorporation", "Incorporated"),
            ("jurisdiction", "Jurisdiction"),
            ("registry_source", "Registry"),
            ("lei", "LEI"),
            ("vat_tax_id", "VAT/Tax ID"),
            ("registered_address", "Address"),
            ("industry_sic", "SIC"),
            ("website", "Website"),
        ]:
            val = (ci.get(key) or "").strip()
            if val:
                rows.append(f"- {label}: {val}")
        if ci.get("business_description"):
            rows.append(f"- Description: {ci['business_description']}")
        if rows:
            sections.append("## Company\n" + "\n".join(rows))

    # ── Verification Checks ───────────────────────────────────────────
    checks = report_content.get("verification_checks") or []
    if checks:
        rows = ["| Check | Result | Notes |", "|---|---|---|"]
        for c in checks[:20]:
            check = (c.get("check") or "").replace("|", "/")
            res = (c.get("result") or "—").replace("|", "/")
            details = (c.get("details") or "").replace("|", "/").replace("\n", " ")
            if len(details) > 90:
                details = details[:87] + "..."
            rows.append(f"| {check} | **{res}** | {details} |")
        sections.append("## Verification Checks\n" + "\n".join(rows))

    # ── Risk Flags ────────────────────────────────────────────────────
    flags = report_content.get("risk_flags") or []
    if flags:
        rows = []
        for f in flags:
            sev = (f.get("severity") or "?").upper()
            title = f.get("title") or "(untitled)"
            desc = (f.get("description") or "").replace("\n", " ")
            if len(desc) > 200:
                desc = desc[:197] + "..."
            action = f.get("recommended_action") or ""
            if len(action) > 120:
                action = action[:117] + "..."
            rid = f.get("flag_id") or "—"
            rows.append(
                f"- **{rid}** [{sev}] **{title}** — {desc}"
                + (f"\n  *Action*: {action}" if action else "")
            )
        sections.append("## Risk Flags\n" + "\n".join(rows))

    # ── Directors / Officers (top recent appointments) ────────────────
    directors = report_content.get("directors_officers") or []
    if directors:
        rows = []
        # Sort by appointment date desc if available; otherwise keep order
        try:
            sorted_dirs = sorted(
                directors,
                key=lambda d: d.get("date_of_appointment") or "",
                reverse=True,
            )
        except Exception:
            sorted_dirs = directors
        for d in sorted_dirs[:5]:
            name = d.get("name") or "(unknown)"
            role = d.get("role") or "—"
            appt = d.get("date_of_appointment") or "—"
            rows.append(f"- {name} · {role} · appointed {appt}")
        if len(directors) > 5:
            rows.append(f"- _(+{len(directors) - 5} more — see full report)_")
        sections.append(
            f"## Directors & Officers ({len(directors)} total)\n" + "\n".join(rows)
        )

    # ── Sanctions coverage summary ────────────────────────────────────
    if cov:
        loaded = cov.get("loaded") or []
        failed = cov.get("failed") or []
        total = cov.get("total") or len(loaded)
        cov_line = (
            f"Screened across {len(loaded)}/{total} active lists: "
            f"{', '.join(loaded) if loaded else '(none)'}"
        )
        if failed:
            cov_line += f". Failed this run: {', '.join(failed)}"
        sections.append("## Sanctions Coverage\n" + cov_line)

    # ── Field availability (Bug 5 disambiguation) ─────────────────────
    field_status = (
        (findings.get("field_status") or {}) if isinstance(findings, dict) else {}
    )
    if field_status:
        found = sorted([k for k, v in field_status.items() if v == "found"])
        clean = sorted([k for k, v in field_status.items() if v == "checked_clean"])
        notrun = sorted([k for k, v in field_status.items() if v == "not_run"])
        parts = []
        if found:
            parts.append(f"**Found data**: {', '.join(found)}")
        if clean:
            parts.append(f"**Checked, clean**: {', '.join(clean)}")
        if notrun:
            parts.append(f"**Not run**: {', '.join(notrun)}")
        if parts:
            sections.append("## Field Coverage\n" + "  \n".join(parts))

    # ── Footer ────────────────────────────────────────────────────────
    sections.append(
        "---\n"
        f"_This is a compact summary. For the full structured report (including all "
        f"{len(directors) if directors else 'N'} directors, full registry crossmatch, "
        f"and adverse media articles), call the SONAR REST API directly:_\n"
        f"```\nGET https://api.getsonar.report/v1/agents/{agent}/run/{run_id}\n"
        f"X-API-Key: <YOUR_SONAR_API_KEY>\n```"
    )

    return "\n\n".join(sections)
