"""Response formatters against the current /v1 shapes (2026-11-06/07):
nothing the model needs is dropped, and the edge cases read correctly."""

from __future__ import annotations

import httpx
from getsonar_mcp import client


def _lookup(**over) -> dict:
    base = {
        "query": {
            "company_name": "Acme SA",
            "registration_number": None,
            "country": "FR",
            "state": None,
        },
        "status": "AMBIGUOUS",
        "found": False,
        "matches": [
            {
                "name": "ACME SA",
                "registration_number": "111111111",
                "status": "active",
                "matched_on": ["name"],
            },
            {
                "name": "ACME SA",
                "registration_number": "222222222",
                "status": "active",
                "matched_on": ["name"],
            },
        ],
        "truncated": True,
        "coverage_note": None,
        "checked_at": "2026-11-07T10:00:00Z",
        "price_cents": 0,
        "free_lookups_remaining": 100,
        "sandbox": False,
        "request_id": "lk_2",
    }
    base.update(over)
    return base


def test_lookup_surfaces_truncated_and_ambiguous() -> None:
    out = client.format_lookup(_lookup())
    assert "**AMBIGUOUS**" in out
    assert "2 active companies" in out
    assert "truncated" in out and "registration_number" in out
    assert "Charged: free" in out
    assert '"222222222"' in out  # full JSON passed through


def test_lookup_surfaces_us_coverage_note_and_sandbox() -> None:
    note = (
        "TX: the Comptroller's active franchise taxpayers, not the formation register"
    )
    out = client.format_lookup(
        _lookup(
            query={
                "company_name": "Acme LLC",
                "registration_number": None,
                "country": "US",
                "state": "TX",
            },
            status="NOT_FOUND",
            matches=[],
            truncated=None,
            coverage_note=note,
            sandbox=True,
            free_lookups_remaining=None,
        )
    )
    assert "(US-TX): **NOT_FOUND**" in out
    assert f"Coverage: {note}" in out
    assert "Sandbox answer" in out
    assert "Charged: free (test key)" in out


def test_lookup_output_is_capped() -> None:
    officers = [
        {"name": f"Officer {i}", "role": "director", "current": True}
        for i in range(2000)
    ]
    out = client.format_lookup(
        _lookup(
            status="FOUND",
            found=True,
            matches=[
                {
                    "name": "ACME SA",
                    "registration_number": "1",
                    "status": "active",
                    "officers": officers,
                }
            ],
        )
    )
    assert len(out) < 23000
    assert "GET /v1/companies/lookup/lk_2" in out


def test_findings_registry_not_searched_is_never_clean() -> None:
    out = client.format_findings(
        {
            "fields": {},
            "fields_found": [],
            "field_status": {
                "corporate_registration": "not_run",
                "sanctions_screening": "checked_clean",
            },
            "registry_match": {
                "status": "NOT_SEARCHED",
                "reason": "COUNTRY_NOT_PROVIDED",
                "matches": [],
            },
        },
        "KYB Screening: Acme",
    )
    assert "Company register: **NOT_SEARCHED**" in out
    assert "COUNTRY_NOT_PROVIDED" in out and "Never read" in out
    assert "**Not run**" in out
    assert "No findings detected across all sources" not in out


def test_findings_company_not_found_and_ubo_graph() -> None:
    out = client.format_findings(
        {
            "fields": {
                "adverse_media": {
                    "confidence": "MEDIUM",
                    "findings": [
                        {
                            "value": "Fined for late filings",
                            "sources": [
                                {
                                    "provider": "news_search",
                                    "url": "https://news.example/a",
                                }
                            ],
                            "source_date": "2025-01-02",
                        }
                    ],
                }
            },
            "fields_found": ["adverse_media"],
            "field_status": {
                "adverse_media": "found",
                "corporate_registration": "company_not_found",
            },
            "ubo_graph": {
                "status": "incomplete",
                "ubos": [
                    {
                        "name": "Jane Doe",
                        "effective_text": "62%",
                        "via": "via Holdco Ltd",
                        "confirmed": True,
                    }
                ],
                "gaps": [
                    {
                        "name": "Offshore Ltd",
                        "text": "Offshore Ltd (VG): owners not published",
                    }
                ],
            },
            "registry_match": {"status": "NOT_FOUND", "country": "GB", "matches": []},
        },
        "KYB Screening: Acme",
    )
    assert "**Company not in the register**" in out
    assert "Company register: **NOT_FOUND** (GB)" in out
    assert "Jane Doe: 62%, via Holdco Ltd" in out
    assert "Gap: Offshore Ltd (VG): owners not published" in out
    assert "Source: news_search https://news.example/a" in out
    assert "Dated: 2025-01-02" in out


def test_failed_run_shows_its_message() -> None:
    # A failed run is a 200 whose ``error`` is the failure text, not the
    # transport-error marker (``error: True``).
    out = client.format_run_status({"status": "failed", "error": "Register timed out"})
    assert out == "Report failed: Register timed out"


def test_sandbox_key_403_says_what_works() -> None:
    out = client.format_findings(
        {
            "error": True,
            "status": 403,
            "message": "SANDBOX_KEY: Test keys work with ...",
        },
        "x",
    )
    assert "company_lookup" in out


def test_error_message_keeps_code_and_reason() -> None:
    resp = httpx.Response(
        400,
        json={
            "detail": {
                "error": {
                    "code": "INVALID_INPUT",
                    "reason": "STATE_NOT_SUPPORTED",
                    "message": "No free register for DE.",
                    "supported_states": ["NY", "TX"],
                }
            }
        },
    )
    msg = client._error_message(resp)
    assert msg.startswith("INVALID_INPUT STATE_NOT_SUPPORTED: No free register for DE.")
    assert "NY, TX" in msg


def test_error_message_reads_validation_errors() -> None:
    resp = httpx.Response(
        422,
        json={
            "detail": [
                {
                    "loc": ["body", "country"],
                    "msg": "String should have at most 2 characters",
                }
            ]
        },
    )
    assert client._error_message(resp) == (
        "Invalid input. country: String should have at most 2 characters"
    )
