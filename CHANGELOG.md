# Changelog

All notable changes to Key49-Fetch will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] — 2026-07-17

### Added

- `src/company_manager.py` — Multi-company CRUD from JSON config
- `src/crypto.py` — Fernet (AES-128-CBC) credential encryption at rest
- `src/rate_limiter.py` — Configurable rate limiting between SRI queries (3 min default)
- `src/session_store.py` — Browser cookie persistence for session reuse
- `src/stats_tracker.py` — Download statistics per company (JSON persistence)
- `src/logger.py` — Structured per-company logging (console + file)
- `src/orchestrator.py` — Multi-company orchestrator with `--health` check
- `config/companies.json` — Sample company configuration file
- Password encryption: `FERNET_KEY` env var enables AES encryption of stored credentials
- Health check: `python -m src.orchestrator --health` for operational monitoring

---

## [0.1.0] — 2026-07-17

### Added

- Initial `sri_downloader.py` script with Playwright + Firefox
- SRI login automation (RUC + password, Keycloak flow)
- reCAPTCHA bypass via native trust scoring (human-like behavior)
- Human-like browsing: menu navigation, mouse movements, scrolls, randomized delays
- Multi-type support: Facturas (1), Liquidación (2), Notas de Crédito (3), Notas de Débito (4), Retenciones (6)
- Auto-retry with exponential backoff (up to 5 attempts)
- Skip already-downloaded files (disk check)
- Download parallelism: up to 3 concurrent HTTP requests
- Browser identity rotation (random user agents and viewports)
- Output structure: `xml_downloads/{ruc}/{month:02d}/{type:02d}/`
- Browser context recycling between document types
- Project documentation: AGENTS.md, ROADMAP.md, PROGRESS.md
