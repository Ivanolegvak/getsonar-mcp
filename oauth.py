"""
OAuth 2.0 Authorization Server for SONAR MCP integration.

Implements the authorization code flow required by Claude's MCP directory.
Users authenticate via SONAR, and receive an access token that maps to their
SONAR API key.

Required callback URLs (from Anthropic):
  - http://localhost:6274/oauth/callback
  - http://localhost:6274/oauth/callback/debug
  - https://claude.ai/api/mcp/auth_callback
  - https://claude.com/api/mcp/auth_callback
"""

import hashlib
import hmac
import os
import secrets
import time
import logging
from urllib.parse import urlencode

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("getsonar-mcp.oauth")

# ── Configuration ────────────────────────────────────────────────────────────

OAUTH_SECRET = os.getenv("OAUTH_SECRET", secrets.token_hex(32))
SONAR_APP_URL = os.getenv("SONAR_APP_URL", "https://getsonar.report")
TOKEN_EXPIRY_SECONDS = 3600 * 24 * 30  # 30 days

# Allowed callback URLs (Anthropic-mandated)
ALLOWED_CALLBACKS = {
    "http://localhost:6274/oauth/callback",
    "http://localhost:6274/oauth/callback/debug",
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
}

# In-memory stores (replace with Redis/DB in production)
_auth_codes: dict[str, dict] = {}  # code -> {api_key, redirect_uri, expires}
_access_tokens: dict[str, dict] = {}  # token -> {api_key, expires}


def _sign(data: str) -> str:
    """HMAC-sign a string."""
    return hmac.new(OAUTH_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()[
        :16
    ]


# ── Authorization endpoint ───────────────────────────────────────────────────


def create_authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Generate the authorization URL that redirects user to SONAR login.

    In production, this redirects to getsonar.report/oauth/authorize where
    the user logs in and approves the connection. For now, returns a direct
    approval URL.
    """
    if redirect_uri not in ALLOWED_CALLBACKS:
        raise ValueError(f"Invalid redirect_uri: {redirect_uri}")

    params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
        }
    )
    return f"{SONAR_APP_URL}/oauth/authorize?{params}"


def issue_auth_code(api_key: str, redirect_uri: str) -> str:
    """Issue an authorization code after user approves the connection.

    Called after user authenticates on SONAR and approves the MCP connection.
    """
    code = secrets.token_urlsafe(32)
    _auth_codes[code] = {
        "api_key": api_key,
        "redirect_uri": redirect_uri,
        "expires": time.time() + 600,  # 10 minutes
    }
    return code


# ── Token endpoint ───────────────────────────────────────────────────────────


def exchange_code_for_token(code: str, redirect_uri: str) -> dict | None:
    """Exchange an authorization code for an access token.

    Returns: {"access_token": "...", "token_type": "bearer", "expires_in": ...}
    or None if invalid.
    """
    entry = _auth_codes.pop(code, None)
    if not entry:
        return None
    if entry["expires"] < time.time():
        return None
    if entry["redirect_uri"] != redirect_uri:
        return None

    # Generate access token
    token = f"sonar_at_{secrets.token_urlsafe(32)}"
    _access_tokens[token] = {
        "api_key": entry["api_key"],
        "expires": time.time() + TOKEN_EXPIRY_SECONDS,
    }

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": TOKEN_EXPIRY_SECONDS,
    }


def validate_token(token: str) -> str | None:
    """Validate an access token and return the associated SONAR API key.

    Returns the API key string, or None if invalid/expired.
    """
    entry = _access_tokens.get(token)
    if not entry:
        return None
    if entry["expires"] < time.time():
        _access_tokens.pop(token, None)
        return None
    return entry["api_key"]


def revoke_token(token: str) -> bool:
    """Revoke an access token."""
    return _access_tokens.pop(token, None) is not None
