"""Webhook dispatcher — notifies ERPs when new documents are downloaded.

Sends signed HTTP POST requests to configured webhook URLs per company.
Includes retry logic, HMAC-SHA256 signatures, and audit logging.

Payload format:
    {
        "event": "documents.downloaded",
        "company_id": "0195160252001",
        "ruc": "0195160252001",
        "period": "2026-07",
        "new_documents": 3,
        "total_documents": 53,
        "timestamp": "2026-07-17T22:00:00Z"
    }
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from src.logger import get_company_logger

# ─── Constants ────────────────────────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds: 2, 4, 8
REQUEST_TIMEOUT = 30  # seconds
AUDIT_DIR = Path("logs/webhooks")


def _sign_payload(payload: dict, secret: str) -> str:
    """Generate HMAC-SHA256 signature of the JSON payload.

    Args:
        payload: The webhook payload dict.
        secret: The webhook secret key.

    Returns:
        Hex-encoded HMAC signature.
    """
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _log_audit(
    company_id: str,
    event: str,
    status: str,
    payload: dict,
    response_status: Optional[int] = None,
    error: Optional[str] = None,
    attempts: int = 1,
) -> None:
    """Append a webhook delivery record to the audit log file.

    Args:
        company_id: Company identifier for log file naming.
        event: Event type (e.g., 'documents.downloaded').
        status: 'success', 'failed', 'retry'.
        payload: The payload that was (or was going to be) sent.
        response_status: HTTP status code from the receiver, if any.
        error: Error message, if any.
        attempts: Number of delivery attempts made.
    """
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    audit_file = AUDIT_DIR / f"{company_id}.jsonl"

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "company_id": company_id,
        "event": event,
        "status": status,
        "attempts": attempts,
        "response_status": response_status,
        "error": error,
        "payload": payload,
    }

    with open(audit_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


async def dispatch_webhook(
    url: str,
    secret: str,
    company_id: str,
    ruc: str,
    period: str,
    new_documents: int,
    total_documents: int,
) -> bool:
    """Send a webhook notification for newly downloaded documents.

    Retries up to MAX_RETRIES with exponential backoff on failure.
    All attempts are logged to the audit trail.

    Args:
        url: The webhook URL to POST to.
        secret: HMAC secret for signing the payload.
        company_id: Company identifier.
        ruc: Company RUC.
        period: Period string (e.g., '2026-07').
        new_documents: Number of newly downloaded documents.
        total_documents: Total documents found (including skipped).

    Returns:
        True if delivery succeeded, False otherwise.
    """
    log = get_company_logger(company_id)
    event = "documents.downloaded"

    payload = {
        "event": event,
        "company_id": company_id,
        "ruc": ruc,
        "period": period,
        "new_documents": new_documents,
        "total_documents": total_documents,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    signature = _sign_payload(payload, secret)
    headers = {
        "Content-Type": "application/json",
        "X-Key49-Signature": signature,
        "X-Key49-Event": event,
        "User-Agent": "Key49-Fetch/0.5.0",
    }

    last_error: Optional[str] = None
    last_status: Optional[int] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                )
                last_status = response.status_code

                if 200 <= response.status_code < 300:
                    log.info(
                        f"📨 Webhook delivered — {url} — "
                        f"status={response.status_code}, attempt={attempt}"
                    )
                    _log_audit(
                        company_id=company_id,
                        event=event,
                        status="success",
                        payload=payload,
                        response_status=response.status_code,
                        attempts=attempt,
                    )
                    return True

                # Server error — may be transient
                log.warning(
                    f"📨 Webhook rejected — {url} — "
                    f"status={response.status_code}, attempt={attempt}"
                )
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"

        except httpx.TimeoutException:
            last_error = "Request timeout"
            log.warning(f"📨 Webhook timeout — {url} — attempt={attempt}")
        except httpx.ConnectError:
            last_error = "Connection refused"
            log.warning(f"📨 Webhook connection failed — {url} — attempt={attempt}")
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            log.error(f"📨 Webhook error — {url}: {e}")

        # Retry with backoff
        if attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF_BASE ** attempt
            log.info(f"📨 Retrying webhook in {wait}s...")
            await _async_sleep(wait)

    # All retries exhausted
    log.error(f"📨 Webhook FAILED after {MAX_RETRIES} attempts — {url}: {last_error}")
    _log_audit(
        company_id=company_id,
        event=event,
        status="failed",
        payload=payload,
        response_status=last_status,
        error=last_error,
        attempts=MAX_RETRIES,
    )
    return False


async def _async_sleep(seconds: float) -> None:
    """Async sleep wrapper (avoids import issues in sync contexts)."""
    import asyncio
    await asyncio.sleep(seconds)
