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
import os
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
from src.stats_tracker import get_stats_tracker
from src.logger import CompanyLogAdapter, get_company_logger, setup_company_logger
from src.webhooks.dispatcher import dispatch_webhook
from src.alerting import send_failure_alert, should_alert, ALERT_THRESHOLD

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
        reuse_sessions: bool = True,
    ) -> None:
        self._company_manager = get_company_manager(config_path)
        self._session_store = get_session_store()
        self._stats_tracker = get_stats_tracker()
        self._output_base = output_base
        self._headless = headless
        self._max_retries = max_retries_per_company
        self._reuse_sessions = reuse_sessions

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
                           Also configurable via COMPANY_FILTER env var
                           (comma-separated company IDs).

        Returns:
            Dict mapping company_id to result summary.
        """
        now = datetime.now(timezone.utc)
        year = year or now.year
        month = month or now.month

        # Resolve company filter: CLI arg > env var > all active
        if company_filter is None:
            env_filter = os.environ.get("COMPANY_FILTER", "").strip()
            if env_filter:
                company_filter = [c.strip() for c in env_filter.split(",") if c.strip()]

        companies = self._company_manager.active_companies
        if company_filter:
            companies = [c for c in companies if c.company_id in company_filter]
            if not companies:
                print(f"⚠️  No active companies match filter: {company_filter}")
                return {}

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

            # Session reuse check
            if self._reuse_sessions:
                session_valid = await self._session_store.is_session_valid(company_id)
                if session_valid:
                    print(f"   🔄 Session reuse: valid cookies found, will attempt fast login")
                else:
                    print(f"   🔐 Session expired or missing, full login required")

            start_time = time.time()

            # Attempt download with retries
            company_result = await self._process_company(
                company, year, month, log
            )
            results[company_id] = company_result

            # Log summary
            duration = time.time() - start_time
            status = "✅" if company_result.get("errors", 0) == 0 else "⚠️"
            
            # Record stats
            period = f"{year}-{month:02d}"
            self._stats_tracker.record_run(
                company_id=company_id,
                downloaded=company_result.get("downloaded", 0),
                skipped=company_result.get("skipped", 0),
                errors=company_result.get("errors", 0),
                duration=duration,
                period=period,
                ruc=company.ruc,
                business_name=company.business_name,
            )

            # Record failure and check alert threshold
            if company_result.get("status") == "max_retries_exceeded":
                self._stats_tracker.record_failure(
                    company_id=company_id,
                    error=f"Max retries ({self._max_retries}) exhausted",
                )
                await self._check_and_alert(company, log)
            
            log.info(
                f"{status} Done in {duration:.0f}s: "
                f"{company_result.get('downloaded', 0)} new, "
                f"{company_result.get('skipped', 0)} skipped, "
                f"{company_result.get('errors', 0)} errors"
            )

            # ── Webhook notification ──────────────────────────────────────
            new_docs = company_result.get("downloaded", 0)
            total_docs = new_docs + company_result.get("skipped", 0)
            period = f"{year}-{month:02d}"

            if company.webhook_url and new_docs > 0:
                log.info(f"📨 Sending webhook to {company.webhook_url}")
                delivered = await dispatch_webhook(
                    url=company.webhook_url,
                    secret=company.webhook_secret or "",
                    company_id=company_id,
                    ruc=company.ruc,
                    period=period,
                    new_documents=new_docs,
                    total_documents=total_docs,
                )
                if delivered:
                    log.info(f"📨 Webhook delivered successfully")
                else:
                    log.warning(f"📨 Webhook delivery failed (check logs/webhooks/)")
            elif company.webhook_url and new_docs == 0:
                log.info(f"📨 Skipping webhook — no new documents")

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

                result = await download_xmls(
                    ano=year,
                    mes=month,
                    tipos_comprobante=company.download_types,
                    output_dir=self._output_base,
                    ruc=company.ruc,
                    clave=company.sri_password_encrypted,
                    headless=self._headless,
                )

                # Use actual counts returned by download_xmls
                if result is None:
                    result = {"status": "ok", "downloaded": 0, "skipped": 0, "errors": 0}

                log.info(
                    f"Download completed — "
                    f"status={result.get('status')}, "
                    f"new={result.get('downloaded', 0)}, "
                    f"skipped={result.get('skipped', 0)}, "
                    f"errors={result.get('errors', 0)}"
                )

                total_downloaded += result.get("downloaded", 0)
                total_skipped += result.get("skipped", 0)
                total_errors += result.get("errors", 0)

                # If no errors or partial success, consider done
                if result.get("status") != "failed":
                    return {
                        "status": result.get("status", "ok"),
                        "downloaded": total_downloaded,
                        "skipped": total_skipped,
                        "errors": total_errors,
                        "attempts": attempt,
                    }
                # If failed but has retries left, continue loop
                log.warning(
                    f"Download returned failed status, "
                    f"will retry ({attempt}/{self._max_retries})"
                )

            except Exception as e:
                log.error(f"Download crashed: {e}")
                total_errors += 1

        return {
            "status": "max_retries_exceeded",
            "downloaded": total_downloaded,
            "skipped": total_skipped,
            "errors": total_errors,
            "attempts": self._max_retries,
        }

    async def _check_and_alert(
        self,
        company: CompanyConfig,
        log: CompanyLogAdapter,
    ) -> None:
        """Check if company has exceeded failure threshold and send alert."""
        should, consecutive, last_err = should_alert(company.company_id)
        if should:
            log.warning(
                f"🚨 Alert threshold reached: {consecutive} consecutive failures "
                f"(threshold={ALERT_THRESHOLD})"
            )
            sent = await send_failure_alert(
                company_id=company.company_id,
                ruc=company.ruc,
                business_name=company.business_name,
                consecutive_failures=consecutive,
                last_error=last_err,
            )
            if sent:
                log.info(f"🚨 Alert sent")
            else:
                log.warning(f"🚨 Alert not sent (no ALERT_WEBHOOK_URL configured)")

    async def backfill(
        self,
        start_year: int,
        start_month: int,
        end_year: int,
        end_month: int,
        company_filter: Optional[list[str]] = None,
    ) -> dict[str, dict]:
        """Download documents for a range of months (historical backfill).

        Useful when onboarding a new company: downloads all past months
        from the start date to the end date.

        Args:
            start_year: First year to download.
            start_month: First month (1-12).
            end_year: Last year to download.
            end_month: Last month (1-12).
            company_filter: Optional list of company_ids.

        Returns:
            Nested dict: {company_id: {period: result}}.
        """
        results: dict[str, dict] = {}

        # Generate month list
        months = []
        y, m = start_year, start_month
        while (y < end_year) or (y == end_year and m <= end_month):
            months.append((y, m))
            m += 1
            if m > 12:
                m = 1
                y += 1

        print(f"\n{'═' * 60}")
        print(f"📅 Backfill mode: {len(months)} months")
        print(f"   From: {start_year}-{start_month:02d}")
        print(f"   To:   {end_year}-{end_month:02d}")
        print(f"{'═' * 60}")

        for period_idx, (year, month) in enumerate(months):
            period = f"{year}-{month:02d}"
            print(f"\n{'─' * 60}")
            print(f"📆 Period {period_idx + 1}/{len(months)}: {period}")
            print(f"{'─' * 60}")

            period_results = await self.run(
                year=year,
                month=month,
                company_filter=company_filter,
            )

            for company_id, result in period_results.items():
                if company_id not in results:
                    results[company_id] = {}
                results[company_id][period] = result

        # Summary
        total_periods = len(months)
        total_docs = sum(
            r.get("downloaded", 0)
            for cr in results.values()
            for r in cr.values()
        )
        print(f"\n{'═' * 60}")
        print(f"🎉 BACKFILL COMPLETE")
        print(f"   Periods: {total_periods} | Documents: {total_docs}")
        print(f"{'═' * 60}")

        return results


    def health_check(self) -> dict:
        """Generate a health status report for all companies.

        Returns:
            Dict with overall status and per-company details.
        """
        stats = self._stats_tracker.health_summary()
        companies_detail = {}
        
        for company in self._company_manager.active_companies:
            cid = company.company_id
            cs = self._stats_tracker.get(cid)
            companies_detail[cid] = {
                "business_name": company.business_name,
                "ruc": company.ruc,
                "is_active": company.is_active,
                "schedule": company.schedule,
                "download_types": company.download_types,
                "last_run_at": cs.last_run_at if cs else None,
                "last_status": cs.last_run_status if cs else "never",
                "total_downloaded": cs.total_downloaded if cs else 0,
                "session_valid": False,  # Checked synchronously here
            }
        
        return {
            "service": "key49-fetch",
            "version": "0.2.0",
            "total_active_companies": len(self._company_manager.active_companies),
            "total_inactive_companies": (
                self._company_manager.company_count
                - len(self._company_manager.active_companies)
            ),
            "companies": companies_detail,
            "rate_limiter": {
                "min_delay_seconds": rate_limiter._min_delay,
                "queries_this_hour": rate_limiter.queries_this_hour,
            },
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
        "--companies", type=str, default=None,
        help="Comma-separated company IDs to process (default: all active). "
             "Also configurable via COMPANY_FILTER env var.",
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
    parser.add_argument(
        "--health", action="store_true", default=False,
        help="Show health check report and exit",
    )
    parser.add_argument(
        "--backfill", type=str, default=None, metavar="YYYY-MM",
        help="Backfill mode: download from START-MONTH to current month. "
             "Example: --backfill 2026-01 downloads Jan 2026 to now.",
    )

    args = parser.parse_args()

    orchestrator = MultiCompanyOrchestrator(
        config_path=args.config,
        output_base=args.output,
        headless=not args.visible,
        max_retries_per_company=args.max_retries,
    )

    if args.health:
        import json as _json
        health = orchestrator.health_check()
        print(_json.dumps(health, indent=2, ensure_ascii=False, default=str))
        return

    # Resolve company filter: --companies flag or COMPANY_FILTER env var
    if args.companies:
        company_filter = [c.strip() for c in args.companies.split(",") if c.strip()]
    else:
        company_filter = None  # Let orchestrator check env var

    # ── Backfill mode ────────────────────────────────────────────────────
    if args.backfill:
        try:
            parts = args.backfill.strip().split("-")
            start_year = int(parts[0])
            start_month = int(parts[1])
        except (ValueError, IndexError):
            print(f"❌ Invalid --backfill format: {args.backfill}")
            print("   Use YYYY-MM (e.g., --backfill 2026-01)")
            sys.exit(1)

        now = datetime.now(timezone.utc)
        await orchestrator.backfill(
            start_year=start_year,
            start_month=start_month,
            end_year=args.year or now.year,
            end_month=args.month or now.month,
            company_filter=company_filter,
        )
        return

    await orchestrator.run(
        year=args.year,
        month=args.month,
        company_filter=company_filter,
    )


if __name__ == "__main__":
    asyncio.run(main())
