"""Key49-Fetch REST API — Companies endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.company_manager import get_company_manager


def list_companies(config_path: str = "config/companies.json") -> list[dict]:
    """List all registered companies with their status and stats."""
    try:
        mgr = get_company_manager(config_path)
    except Exception:
        return []

    from src.stats_tracker import get_stats_tracker

    stats_tracker = get_stats_tracker()
    companies = []

    for company in mgr.active_companies:
        stats = stats_tracker.get(company.company_id)
        companies.append({
            "company_id": company.company_id,
            "ruc": company.ruc,
            "business_name": company.business_name,
            "is_active": company.is_active,
            "download_types": company.download_types,
            "schedule": company.schedule,
            "last_run_at": stats.last_run_at.isoformat() if stats and stats.last_run_at else None,
            "last_run_status": stats.last_run_status if stats else "never",
            "total_downloaded": stats.total_downloaded if stats else 0,
            "total_skipped": stats.total_skipped if stats else 0,
            "total_errors": stats.total_errors if stats else 0,
            "consecutive_failures": stats.consecutive_failures if stats else 0,
            "last_error": stats.last_error if stats else "",
        })

    return companies
