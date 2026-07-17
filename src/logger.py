"""Structured logging for multi-company operations.

Provides per-company log files and console output with consistent formatting.
In production this will emit JSON logs for ELK/Loki ingestion.

Uses Python's built-in logging with custom formatting.

Standards:
    - All identifiers in English, snake_case
    - Type hints on all functions
    - Docstrings on public functions
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


LOG_DIR = Path("logs")
LOG_FORMAT = (
    "%(asctime)s | %(levelname)-7s | %(company_id)-14s | %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class CompanyFormatter(logging.Formatter):
    """Custom formatter that includes company_id in log records."""

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "company_id"):
            record.company_id = "-"
        return super().format(record)


def setup_company_logger(
    company_id: str,
    log_dir: str | Path = LOG_DIR,
    level: int = logging.INFO,
) -> logging.Logger:
    """Create a logger that writes to both console and a per-company file.

    Args:
        company_id: Company identifier for log file naming.
        log_dir: Directory for log files.
        level: Logging level.

    Returns:
        Configured logger instance.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"key49fetch.{company_id}")
    logger.setLevel(level)
    logger.propagate = False  # Don't bubble up to root logger

    # Avoid duplicate handlers on re-configuration
    if logger.handlers:
        return logger

    formatter = CompanyFormatter(LOG_FORMAT, DATE_FORMAT)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler (per company)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    file_path = log_path / f"{company_id}-{today}.log"
    file_handler = logging.FileHandler(file_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def get_company_logger(company_id: str) -> logging.Logger:
    """Get or create a logger for a specific company.

    Args:
        company_id: Company identifier.

    Returns:
        Logger instance (creates one if it doesn't exist).
    """
    logger_name = f"key49fetch.{company_id}"
    logger = logging.getLogger(logger_name)
    if not logger.handlers:
        return setup_company_logger(company_id)
    return logger


class CompanyLogAdapter(logging.LoggerAdapter):
    """Adapter that injects company_id into every log call."""

    def __init__(
        self, logger: logging.Logger, company_id: str
    ) -> None:
        super().__init__(logger, {"company_id": company_id})

    def process(
        self, msg: str, kwargs: dict
    ) -> tuple[str, dict]:
        if "extra" not in kwargs:
            kwargs["extra"] = {}
        kwargs["extra"]["company_id"] = self.extra.get("company_id", "-")
        return msg, kwargs
