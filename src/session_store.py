"""Session persistence for SRI browser cookies.

Saves and loads Playwright browser context state (cookies, localStorage)
so we can reuse authenticated sessions across runs, avoiding re-login
and reducing reCAPTCHA friction.

Standards:
    - All identifiers in English, snake_case
    - Type hints on all functions
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from playwright.async_api import BrowserContext


DEFAULT_SESSION_DIR = Path("cookies")


class SessionStore:
    """Persists and restores SRI browser sessions."""

    def __init__(self, base_dir: str | Path = DEFAULT_SESSION_DIR) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, company_id: str) -> Path:
        """Get the session file path for a company."""
        return self._base_dir / f"{company_id}.json"

    async def save(self, context: BrowserContext, company_id: str) -> None:
        """Save browser context state (cookies, storage) to disk.

        Args:
            context: Playwright browser context with active SRI session.
            company_id: Company identifier for the session file name.
        """
        cookies = await context.cookies()
        # Filter only SRI-relevant cookies
        sri_cookies = [
            c for c in cookies
            if "sri" in c.get("domain", "").lower()
            or "srienlinea" in c.get("domain", "").lower()
        ]

        state = {
            "company_id": company_id,
            "cookies": sri_cookies,
            "saved_at": None,  # Will be set by caller if needed
        }

        path = self._session_path(company_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)

    async def load(
        self, context: BrowserContext, company_id: str
    ) -> bool:
        """Load cookies into the browser context.

        Args:
            context: Playwright browser context.
            company_id: Company identifier.

        Returns:
            True if cookies were loaded, False if no session file exists.
        """
        path = self._session_path(company_id)
        if not path.exists():
            return False

        try:
            with open(path, encoding="utf-8") as f:
                state = json.load(f)

            cookies = state.get("cookies", [])
            if cookies:
                await context.add_cookies(cookies)
                return True
        except (json.JSONDecodeError, KeyError, OSError):
            pass

        return False

    async def is_session_valid(self, company_id: str) -> bool:
        """Check if a saved session exists and is recent.

        A session is considered valid if saved within the last 4 hours
        (SRI sessions typically last 5 hours).
        """
        path = self._session_path(company_id)
        if not path.exists():
            return False

        try:
            mtime = os.path.getmtime(path)
            age_seconds = __import__("time").time() - mtime
            return age_seconds < 4 * 3600  # 4 hours
        except OSError:
            return False

    def delete(self, company_id: str) -> None:
        """Delete a stored session."""
        path = self._session_path(company_id)
        if path.exists():
            path.unlink()

    def delete_all(self) -> int:
        """Delete all stored sessions. Returns count of deleted files."""
        count = 0
        for f in self._base_dir.glob("*.json"):
            f.unlink()
            count += 1
        return count


# Singleton
_session_store: Optional[SessionStore] = None


def get_session_store(
    base_dir: str | Path = DEFAULT_SESSION_DIR,
) -> SessionStore:
    """Get or create the singleton SessionStore."""
    global _session_store
    if _session_store is None:
        _session_store = SessionStore(base_dir)
    return _session_store
