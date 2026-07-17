"""Rate limiter for SRI queries.

Ensures minimum gaps between requests to avoid IP reputation
degradation and reCAPTCHA blocks. Configurable per environment.

Standards:
    - All identifiers in English, snake_case
    - Type hints on all functions
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict


class RateLimiter:
    """Enforces minimum delay between SRI queries.

    Tracks last query time globally and optionally per proxy profile.
    """

    def __init__(
        self,
        min_delay_seconds: float = 180.0,  # 3 minutes default
        max_delay_seconds: float = 600.0,  # 10 minutes max
    ) -> None:
        self._min_delay = min_delay_seconds
        self._max_delay = max_delay_seconds
        self._last_query_time: float = 0.0
        self._proxy_last_query: dict[str, float] = defaultdict(float)
        self._query_count: int = 0
        self._query_count_window: float = time.time()

    @property
    def queries_this_hour(self) -> int:
        """Return number of queries in the current rolling hour window."""
        if time.time() - self._query_count_window > 3600:
            self._query_count = 0
            self._query_count_window = time.time()
        return self._query_count

    async def wait_if_needed(
        self, proxy_profile: str | None = None
    ) -> float:
        """Wait the required delay before the next query.

        Args:
            proxy_profile: Optional proxy profile name for per-proxy tracking.

        Returns:
            Seconds actually waited.
        """
        now = time.time()

        # Determine which last-query time to use
        if proxy_profile:
            last_time = self._proxy_last_query[proxy_profile]
        else:
            last_time = self._last_query_time

        elapsed = now - last_time
        remaining = max(0.0, self._min_delay - elapsed)

        if remaining > 0:
            await asyncio.sleep(remaining)

        waited = max(remaining, 0.0)
        self._record_query(proxy_profile)
        return waited

    def _record_query(self, proxy_profile: str | None = None) -> None:
        """Record that a query just happened."""
        now = time.time()
        if proxy_profile:
            self._proxy_last_query[proxy_profile] = now
        else:
            self._last_query_time = now
        self._query_count += 1

    def estimate_next_slot(self, proxy_profile: str | None = None) -> float:
        """Estimate seconds until the next available query slot."""
        now = time.time()
        if proxy_profile:
            last = self._proxy_last_query.get(proxy_profile, 0.0)
        else:
            last = self._last_query_time
        return max(0.0, self._min_delay - (now - last))


# Default instance with 3-minute minimum between queries
rate_limiter = RateLimiter(min_delay_seconds=180.0)
