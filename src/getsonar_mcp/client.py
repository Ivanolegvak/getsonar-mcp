"""HTTP client + response formatters for the SONAR public API.

Shared by both stdio and streamable-http MCP transports. The transport
layer just wires up tool dispatch; this module owns the actual API calls.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("getsonar-mcp.client")

# Public-API base URL. Custom-domain default — overridable for staging /
# self-hosted deployments via env.
DEFAULT_API_BASE = "https://api.getsonar.report"

DEFAULT_TIMEOUT_S = 120

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
                "The /findings endpoint usually responds in 30-90s; if "
                "you're consistently timing out, raise SONAR_API_TIMEOUT."
            ),
        }
    except httpx.RequestError as e:
        return {
            "error": True,
            "status": 0,
            "message": f"Network error calling {path}: {type(e).__name__}",
        }

    if resp.status_code != 200 and resp.status_code != 202:
        try:
            err = resp.json()
            # The SONAR public API wraps errors as
            # {"detail": {"error": {"code": str, "message": str, ...}}}
            msg = (
                err.get("detail", {}).get("error", {}).get("message")
                or err.get("detail")
                or resp.text
            )
        except Exception:
            msg = resp.text
        return {
            "error": True,
            "status": resp.status_code,
            "message": str(msg)[:400],
        }

    try:
        return resp.json()
    except ValueError:
        return {
            "error": True,
            "status": resp.status_code,
            "message": "non-JSON response",
        }


# ── Response formatters ──────────────────────────────────────────────────────


def format_findings(result: dict, title: str) -> str:
    """Format a /findings API response as readable Markdown for the LLM.

    Phase AD3 follow-up (2026-05-09) — Bug 9 fix:
      Added (a) field_status 3-state surfacing (Bug 5), and
      (b) a hard 22 KB output cap to stay safely under MCP's
      ~25 KB transport boundary even for big reports.
    """
    if result.get("error"):
        # Surface a friendly 402 message verbatim — it includes top-up URL
        # and the customer needs to see it
        if result.get("status") == 402:
            return f"⚠️  Insufficient balance.\n\n{result.get('message', '')}"
        return (
            f"⚠️  SONAR API error (HTTP {result.get('status', '?')}).\n\n"
            f"{result.get('message', 'unknown error')}"
        )

    fields = result.get("fields", {})
    found = result.get("fields_found", []) or []
    not_found = result.get("fields_not_found", []) or []
    field_status = result.get("field_status", {}) or {}
    sources = result.get("sources_checked", 0)
    time_ms = result.get("processing_time_ms", 0)

    parts = [
        f"# {title}",
        f"Sources checked: {sources} · Processing time: {time_ms}ms",
    ]

    # Phase AD3 — surface the 3-state field_status when present (post Bug 5).
    # Falls back to legacy fields_found / fields_not_found split if the
    # backend hasn't been upgraded yet.
    if field_status:
        clean = sorted([k for k, v in field_status.items() if v == "checked_clean"])
        notrun = sorted([k for k, v in field_status.items() if v == "not_run"])
        if found:
            parts.append(f"**Found data**: {', '.join(found)}")
        if clean:
            parts.append(
                f"**Checked, clean** (no findings — collector ran): {', '.join(clean)}"
            )
        if notrun:
            parts.append(
                f"**Not run** (collector disabled or unmapped for this agent): {', '.join(notrun)}"
            )
    else:
        parts.append(f"Fields with data: {', '.join(found) if found else 'none'}")
        if not_found:
            parts.append(f"No data for: {', '.join(not_found)}")
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
                sources_list = f.get("sources", []) or []
                url = sources_list[0].get("url", "") if sources_list else ""
                parts.append(f"- **{value}**")
                if detail:
                    parts.append(f"  {detail}")
                if url:
                    parts.append(f"  Source: {url}")
            parts.append("")

    if not found:
        parts.append("No findings detected across all sources.")

    out = "\n".join(parts)

    # Hard cap to stay under MCP transport boundary. Truncate at a clean
    # boundary if we'd exceed the cap — better than mid-string clip.
    _MAX_BYTES = 22000
    if len(out) > _MAX_BYTES:
        # Find the last paragraph break before the cap
        cut = out[:_MAX_BYTES].rsplit("\n\n", 1)[0]
        out = cut + (
            "\n\n"
            "---\n"
            "_(response truncated — full report exceeds MCP transport boundary. "
            "Fetch via REST API: "
            "`GET /v1/agents/<agent>/findings` with the same arguments)_"
        )

    return out


def format_run_started(result: dict, agent_type: str) -> str:
    """Format the /run async-submit response."""
    if result.get("error"):
        if result.get("status") == 402:
            return f"⚠️  Insufficient balance.\n\n{result.get('message', '')}"
        return (
            f"⚠️  Failed to start report (HTTP {result.get('status', '?')}).\n\n"
            f"{result.get('message', '')}"
        )

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
    if result.get("error"):
        return (
            f"⚠️  Failed to check report status (HTTP {result.get('status', '?')}).\n\n"
            f"{result.get('message', '')}"
        )

    status = result.get("status", "unknown")
    if status == "completed":
        return _format_completed_report(result)
    if status == "failed":
        err = result.get("error_message") or result.get("error") or "Unknown error"
        return f"Report failed: {err}"
    return f"Report status: {status}. Still processing — check again in 15-30 seconds."


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
