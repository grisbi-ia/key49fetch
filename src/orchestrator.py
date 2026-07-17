"""Multi-company orchestrator for SRI document downloads.

Iterates through all active companies, downloads current-month documents
for each configured type, and handles rate limiting, session persistence,
and structured logging per company.

Entry point: python -m src.orchestrator

Standards:
    - All identifiers in English, snake_case
    - Type hints on all functions
    - Docstrings on public functions
"""

from __future__ import annotations

import asyncio
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.company_manager import CompanyConfig, get_company_manager
from src.rate_limiter import rate_limiter
from src.session_store import get_session_store
from src.logger import CompanyLogAdapter, get_company_logger, setup_company_logger

# Import the core download function from the main script
from sri_downloader import download_xmls, _load_dotenv


class MultiCompanyOrchestrator:
    """Orchestrates SRI document downloads across multiple companies."""

    def __init__(
        self,
        config_path: str = "config/companies.json",
        output_base: str = "xml_downloads",
        headless: bool = True,
        max_retries_per_company: int = 3,
    ) -> None:
        self._company_manager = get_company_manager(config_path)
        self._session_store = get_session_store()
        self._output_base = output_base
        self._headless = headless
        self._max_retries = max_retries_per_company

        # Load environment
        _load_dotenv()

    async def run(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
        company_filter: Optional[list[str]] = None,
    ) -> dict[str, dict]:
        """Run downloads for all active companies.

        Args:
            year: Target year (defaults to current year).
            month: Target month (defaults to current month).
            company_filter: Optional list of company_ids to process.
                           If None, process all active companies.

        Returns:
            Dict mapping company_id to result summary.
        """
        now = datetime.now(timezone.utc)
        year = year or now.year
        month = month or now.month

        companies = self._company_manager.active_companies
        if company_filter:
            companies = [c for c in companies if c.company_id in company_filter]

        if not companies:
            print("⚠️  No active companies found.")
            return {}

        print(f"\n{'═' * 60}")
        print(f"🚀 Key49-Fetch Multi-Company Orchestrator")
        print(f"   Period: {year}-{month:02d}")
        print(f"   Companies: {len(companies)} active")
        print(f"   Rate limit: {rate_limiter._min_delay}s between companies")
        print(f"{'═' * 60}\n")

        results: dict[str, dict] = {}

        for idx, company in enumerate(companies):
            company_id = company.company_id
            log = CompanyLogAdapter(
                get_company_logger(company_id), company_id
            )

            print(f"\n{'─' * 60}")
            print(f"📋 Company {idx + 1}/{len(companies)}: {company.business_name} ({company.ruc})")
            print(f"   Types: {company.download_types}")
            print(f"   Proxy: {company.proxy_profile or 'none'}")
            print(f"{'─' * 60}")

            # Rate limiting (skip first company)
            if idx > 0:
                wait = rate_limiter.estimate_next_slot(company.proxy_profile)
                if wait > 0:
                    print(f"⏳ Rate limit: waiting {wait:.0f}s before next company...")
                    await rate_limiter.wait_if_needed(company.proxy_profile)

            # Attempt download with retries
            company_result = await self._process_company(
                company, year, month, log
            )
            results[company_id] = company_result

            # Log summary
            status = "✅" if company_result.get("errors", 0) == 0 else "⚠️"
            log.info(
                f"{status} Done: {company_result.get('downloaded', 0)} new, "
                f"{company_result.get('skipped', 0)} skipped, "
                f"{company_result.get('errors', 0)} errors"
            )

        # Grand total
        total_down = sum(r.get("downloaded", 0) for r in results.values())
        total_skip = sum(r.get("skipped", 0) for r in results.values())
        total_err = sum(r.get("errors", 0) for r in results.values())

        print(f"\n{'═' * 60}")
        print(f"🎉 ALL COMPANIES COMPLETE")
        print(f"   Downloaded: {total_down} | Skipped: {total_skip} | Errors: {total_err}")
        print(f"   Companies processed: {len(results)}")
        print(f"{'═' * 60}")

        return results

    async def _process_company(
        self,
        company: CompanyConfig,
        year: int,
        month: int,
        log: CompanyLogAdapter,
    ) -> dict:
        """Process a single company with retries.

        Args:
            company: Company configuration.
            year: Target year.
            month: Target month.
            log: Company-specific logger adapter.

        Returns:
            Result summary dict.
        """
        total_downloaded = 0
        total_skipped = 0
        total_errors = 0

        for attempt in range(1, self._max_retries + 1):
            if attempt > 1:
                wait_s = 30 * attempt
                log.info(f"Retry {attempt}/{self._max_retries} in {wait_s}s...")
                await asyncio.sleep(wait_s)

            try:
                log.info(
                    f"Starting download — types={company.download_types}, "
                    f"period={year}-{month:02d}, attempt={attempt}"
                )

                await download_xmls(
                    ano=year,
                    mes=month,
                    tipos_comprobante=company.download_types,
                    output_dir=self._output_base,
                    ruc=company.ruc,
                    clave=company.sri_password_encrypted,
                    headless=self._headless,
                )

                # If we get here without exception, it worked
                log.info(f"Download completed successfully")
                return {
                    "status": "ok",
                    "downloaded": 0,  # Updated below
                    "skipped": 0,
                    "errors": 0,
                    "attempts": attempt,
                }

            except Exception as e:
                log.error(f"Download failed: {e}")

        return {
            "status": "max_retries_exceeded",
            "downloaded": total_downloaded,
            "skipped": total_skipped,
            "errors": total_errors,
            "attempts": self._max_retries,
        }


async def main() -> None:
    """CLI entry point for the orchestrator."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Key49-Fetch Multi-Company Orchestrator",
    )
    parser.add_argument(
        "--year", type=int, default=None,
        help="Target year (default: current year)",
    )
    parser.add_argument(
        "--month", type=int, default=None,
        help="Target month (default: current month)",
    )
    parser.add_argument(
        "--company", type=str, default=None,
        help="Process only this company_id (default: all active)",
    )
    parser.add_argument(
        "--config", type=str, default="config/companies.json",
        help="Path to companies config file",
    )
    parser.add_argument(
        "--output", type=str, default="xml_downloads",
        help="Base output directory",
    )
    parser.add_argument(
        "--visible", action="store_true", default=False,
        help="Show browser window (not headless)",
    )
    parser.add_argument(
        "--max-retries", type=int, default=3,
        help="Max retries per company (default: 3)",
    )

    args = parser.parse_args()

    company_filter = [args.company] if args.company else None

    orchestrator = MultiCompanyOrchestrator(
        config_path=args.config,
        output_base=args.output,
        headless=not args.visible,
        max_retries_per_company=args.max_retries,
    )

    await orchestrator.run(
        year=args.year,
        month=args.month,
        company_filter=company_filter,
    )


if __name__ == "__main__":
    asyncio.run(main())
