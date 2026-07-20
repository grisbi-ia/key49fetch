"""Download statistics tracker per company.

Tracks download history for each company: last run, document counts,
success/failure rates. Persisted as JSON for simplicity.

Standards:
    - All identifiers in English, snake_case
    - Type hints on all functions
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


STATS_PATH = Path("config/stats.json")


@dataclass
class CompanyStats:
    """Download statistics for a single company."""

    company_id: str
    ruc: str = ""
    business_name: str = ""
    total_downloaded: int = 0
    total_skipped: int = 0
    total_errors: int = 0
    last_run_at: Optional[str] = None
    last_run_status: str = "never"
    last_run_duration_seconds: float = 0.0
    months_processed: list[str] = field(default_factory=list)

    def record_run(
        self,
        downloaded: int,
        skipped: int,
        errors: int,
        duration: float,
        period: str,
    ) -> None:
        """Record a completed download run."""
        self.total_downloaded += downloaded
        self.total_skipped += skipped
        self.total_errors += errors
        self.last_run_at = datetime.now(timezone.utc).isoformat()
        self.last_run_status = "ok" if errors == 0 else "partial"
        self.last_run_duration_seconds = duration
        if period not in self.months_processed:
            self.months_processed.append(period)
            self.months_processed.sort()


class StatsTracker:
    """Tracks download statistics for all companies."""

    def __init__(self, stats_file: str | Path = STATS_PATH) -> None:
        self._path = Path(stats_file)
        self._stats: dict[str, CompanyStats] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with open(self._path, encoding="utf-8") as f:
            raw = json.load(f)
        for company_id, data in raw.items():
            self._stats[company_id] = CompanyStats(**data)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            cid: {
                "company_id": s.company_id,
                "ruc": s.ruc,
                "business_name": s.business_name,
                "total_downloaded": s.total_downloaded,
                "total_skipped": s.total_skipped,
                "total_errors": s.total_errors,
                "last_run_at": s.last_run_at,
                "last_run_status": s.last_run_status,
                "last_run_duration_seconds": s.last_run_duration_seconds,
                "months_processed": s.months_processed,
                "consecutive_failures": s.consecutive_failures,
                "last_error": s.last_error,
            }
            for cid, s in self._stats.items()
        }
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False, default=str)

    def get_or_create(
        self, company_id: str, ruc: str = "", business_name: str = ""
    ) -> CompanyStats:
        """Get stats for a company, creating them if they don't exist."""
        if company_id not in self._stats:
            self._stats[company_id] = CompanyStats(
                company_id=company_id,
                ruc=ruc,
                business_name=business_name,
            )
        return self._stats[company_id]

    def get(self, company_id: str) -> Optional[CompanyStats]:
        """Get stats for a company, or None."""
        return self._stats.get(company_id)

    def get_all(self) -> dict[str, CompanyStats]:
        """Get all company stats."""
        return dict(self._stats)

    def record_run(
        self,
        company_id: str,
        downloaded: int,
        skipped: int,
        errors: int,
        duration: float,
        period: str,
        ruc: str = "",
        business_name: str = "",
    ) -> None:
        """Record a completed run for a company."""
        stats = self.get_or_create(company_id, ruc, business_name)
        stats.record_run(downloaded, skipped, errors, duration, period)
        self._save()

    def record_failure(
        self,
        company_id: str,
        error: str,
    ) -> None:
        """Record a failed run (after all retries exhausted)."""
        stats = self.get_or_create(company_id)
        stats.record_failure(error)
        self._save()

    def health_summary(self) -> dict:
        """Generate a health summary for all companies."""
        companies = {}
        for cid, s in self._stats.items():
            companies[cid] = {
                "business_name": s.business_name,
                "last_run_at": s.last_run_at,
                "last_status": s.last_run_status,
                "total_downloaded": s.total_downloaded,
            }
        return {
            "total_companies": len(self._stats),
            "companies": companies,
        }


# Singleton
_stats_tracker: Optional[StatsTracker] = None


def get_stats_tracker(
    stats_file: str | Path = STATS_PATH,
) -> StatsTracker:
    """Get or create the singleton StatsTracker."""
    global _stats_tracker
    if _stats_tracker is None:
        _stats_tracker = StatsTracker(stats_file)
    return _stats_tracker
