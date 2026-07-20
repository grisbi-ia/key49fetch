"""Company configuration manager.

Loads and manages multi-company configurations from a JSON file.
In production this will be replaced by a database (PostgreSQL).

Standards:
    - All identifiers in English, snake_case
    - Type hints on all functions
    - Docstrings on public functions
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.crypto import encrypt_password, decrypt_password


@dataclass
class CompanyConfig:
    """Configuration for a single company (tenant)."""

    company_id: str
    ruc: str
    business_name: str
    sri_password_encrypted: str
    is_active: bool = True
    download_types: list[int] = field(default_factory=lambda: [1, 6])
    schedule: str = "daily"
    proxy_profile: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.ruc or len(self.ruc) not in (10, 13):
            raise ValueError(f"Invalid RUC (must be 10 or 13 digits): {self.ruc}")
        if len(self.ruc) == 10:
            # Auto-pad cédula to RUC format (cédula + 001)
            self.ruc = self.ruc + "001"
        if not self.sri_password_encrypted:
            raise ValueError("SRI password is required")


class CompanyManager:
    """Loads and manages company configurations from a JSON file."""

    def __init__(self, config_path: str | Path = "config/companies.json") -> None:
        self._config_path = Path(config_path)
        self._companies: dict[str, CompanyConfig] = {}
        self._load()

    def _load(self) -> None:
        """Load company configurations from the JSON file."""
        if not self._config_path.exists():
            raise FileNotFoundError(
                f"Company config not found: {self._config_path}"
            )

        with open(self._config_path, encoding="utf-8") as f:
            raw_list: list[dict] = json.load(f)

        for raw in raw_list:
            # Support env var override for password: SRI_PASSWORD_{RUC}
            env_key = f"SRI_PASSWORD_{raw['ruc']}"
            stored_password = raw.get("sri_password_encrypted", "")

            # Decrypt stored password (or use env override)
            if os.environ.get(env_key):
                password = os.environ[env_key]
            else:
                password = decrypt_password(stored_password)

            company = CompanyConfig(
                company_id=raw.get("company_id", raw["ruc"]),
                ruc=raw["ruc"],
                business_name=raw.get("business_name", raw["ruc"]),
                sri_password_encrypted=password,  # Always plain text in memory
                is_active=raw.get("is_active", True),
                download_types=raw.get("download_types", [1, 6]),
                schedule=raw.get("schedule", "daily"),
                proxy_profile=raw.get("proxy_profile"),
                webhook_url=raw.get("webhook_url"),
                webhook_secret=raw.get("webhook_secret"),
            )
            self._companies[company.company_id] = company

    @property
    def active_companies(self) -> list[CompanyConfig]:
        """Return all active companies."""
        return [c for c in self._companies.values() if c.is_active]

    @property
    def company_count(self) -> int:
        """Return total number of companies (including inactive)."""
        return len(self._companies)

    def get(self, company_id: str) -> CompanyConfig:
        """Get a company by its ID. Raises KeyError if not found."""
        if company_id not in self._companies:
            raise KeyError(f"Company not found: {company_id}")
        return self._companies[company_id]

    def get_active(self, company_id: str) -> CompanyConfig:
        """Get an active company by ID. Raises ValueError if inactive or not found."""
        company = self.get(company_id)
        if not company.is_active:
            raise ValueError(f"Company is inactive: {company_id}")
        return company

    def add(self, company: CompanyConfig) -> None:
        """Add a new company and persist to disk."""
        self._companies[company.company_id] = company
        self._save()

    def update(self, company_id: str, **kwargs) -> None:
        """Update company fields and persist to disk."""
        if company_id not in self._companies:
            raise KeyError(f"Company not found: {company_id}")
        company = self._companies[company_id]
        for key, value in kwargs.items():
            if hasattr(company, key):
                setattr(company, key, value)
        self._save()

    def remove(self, company_id: str) -> None:
        """Remove a company and persist to disk."""
        if company_id not in self._companies:
            raise KeyError(f"Company not found: {company_id}")
        del self._companies[company_id]
        self._save()

    def _save(self) -> None:
        """Persist current companies to the JSON file."""
        raw_list = []
        for c in self._companies.values():
            raw_list.append({
                "company_id": c.company_id,
                "ruc": c.ruc,
                "business_name": c.business_name,
                "sri_password_encrypted": encrypt_password(c.sri_password_encrypted),
                "is_active": c.is_active,
                "download_types": c.download_types,
                "schedule": c.schedule,
                "proxy_profile": c.proxy_profile,
                "webhook_url": c.webhook_url,
                "webhook_secret": c.webhook_secret,
            })

        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(raw_list, f, indent=4, ensure_ascii=False)


# Singleton instance
_company_manager: Optional[CompanyManager] = None


def get_company_manager(config_path: str | Path = "config/companies.json") -> CompanyManager:
    """Get or create the singleton CompanyManager instance."""
    global _company_manager
    if _company_manager is None:
        _company_manager = CompanyManager(config_path)
    return _company_manager
