"""Failure alerting — sends notifications on repeated download failures.

When a company accumulates N consecutive failures, an alert webhook is fired
to notify operators (Slack, Telegram, email, or custom endpoint).

Configure via env vars:
    ALERT_WEBHOOK_URL   — Global alert webhook URL
    ALERT_THRESHOLD     — Consecutive failures before alert (default: 3)
"""

from __future__ import annotations

import os
from typing import Optional

from src.webhooks.dispatcher import _sign_payload

import httpx

ALERT_THRESHOLD = int(os.environ.get("ALERT_THRESHOLD", "3"))
REQUEST_TIMEOUT = 15


async def send_failure_alert(
    company_id: str,
    ruc: str,
    business_name: str,
    consecutive_failures: int,
    last_error: str,
    alert_url: Optional[str] = None,
) -> bool:
    """Send an alert about consecutive download failures.

    Args:
        company_id: Company identifier.
        ruc: Company RUC.
        business_name: Company name.
        consecutive_failures: Number of consecutive failures.
        last_error: Last error message.
        alert_url: Override URL (falls back to ALERT_WEBHOOK_URL env var).

    Returns:
        True if alert was sent, False otherwise.
    """
    url = alert_url or os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return False

    payload = {
        "event": "alert.consecutive_failures",
        "company_id": company_id,
        "ruc": ruc,
        "business_name": business_name,
        "consecutive_failures": consecutive_failures,
        "threshold": ALERT_THRESHOLD,
        "last_error": last_error,
        "severity": "critical" if consecutive_failures >= ALERT_THRESHOLD * 2 else "warning",
    }

    # Sign if secret is configured
    secret = os.environ.get("ALERT_WEBHOOK_SECRET", "")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Key49-Fetch-Alert/0.6.0",
    }
    if secret:
        headers["X-Key49-Signature"] = _sign_payload(payload, secret)

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=headers)
            return 200 <= response.status_code < 300
    except Exception:
        return False


def should_alert(company_id: str) -> tuple[bool, int, str]:
    """Check if a company has exceeded the failure threshold.

    Reads the stats tracker to count consecutive failures.

    Args:
        company_id: Company identifier.

    Returns:
        Tuple of (should_alert, consecutive_failures, last_error).
    """
    import json
    from pathlib import Path

    stats_file = Path("config/stats.json")
    if not stats_file.exists():
        return False, 0, ""

    try:
        with open(stats_file, encoding="utf-8") as f:
            stats = json.load(f)
    except Exception:
        return False, 0, ""

    cs = stats.get(company_id, {})
    consecutive = cs.get("consecutive_failures", 0)
    last_error = cs.get("last_error", "")

    return consecutive >= ALERT_THRESHOLD, consecutive, last_error
