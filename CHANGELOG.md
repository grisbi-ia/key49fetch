# Changelog

All notable changes to Key49-Fetch will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
