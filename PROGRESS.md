# Key49-Fetch — Progress Log

> Last updated: 2026-07-17

---

## Phase 0 — Foundation (v0.1.0) ✅ COMPLETED

**Tag**: `v0.1.0`  
**Completed**: 2026-07-17

### Summary

Standalone Python script that automates SRI document downloads using Playwright + Firefox with human-like behavior simulation. Successfully downloads XMLs and PDFs for Facturas (type 1) and Retenciones (type 6) across multiple months.

### Key Achievements

- **SRI login**: Automated RUC + password entry with Keycloak redirect handling
- **reCAPTCHA**: Native trust scoring approach (human-like browsing, menu navigation, mouse movements, scrolls, randomized delays) — CapSolver removed as it was rejected by SRI
- **Multi-type support**: Queries and downloads Facturas, Retenciones, Notas de Crédito, Notas de Débito, Liquidaciones
- **Skip existing files**: Checks disk before download, avoids redundant HTTP requests
- **Retry logic**: Up to 5 retries with exponential backoff (10s → 15s → 20s → 25s → 30s)
- **Human behavior**: Menu-based navigation (perfil → accederAplicacion), mouse movements with random steps, scroll simulation, variable delays
- **Output structure**: `xml_downloads/{ruc}/{month:02d}/{type:02d}/`

### Test Results (Company: 0195160252001)

| Month | Type | Files | Attempts | Status |
|-------|------|-------|----------|--------|
| Abril | Facturas | 12 (6 XML + 6 PDF) | 2 | ✅ |
| Abril | Retenciones | 4 (2 XML + 2 PDF) | 2 | ✅ |
| Abril | Notas Crédito | 0 (no data) | 6 | ✅ |
| Mayo | Facturas | 16 (8 XML + 8 PDF) | 2 | ✅ |
| Mayo | Retenciones | 4 (2 XML + 2 PDF) | 4 | ✅ |
| Junio | Facturas | 12 (6 XML + 6 PDF) | 6 | ✅ |
| Junio | Retenciones | 4 (2 XML + 2 PDF) | 2 | ✅ |

### Known Issues

- **IP reputation degradation**: Consecutive queries from same IP cause increasing reCAPTCHA rejections (2 attempts for April → 6 for June)
- **No session reuse**: Fresh login per company per execution wastes time and SRI resources
- **No proxy support**: Single IP for all requests

### Files Changed

- `sri_downloader.py` — Main script (~1200 lines)
- `.env` — CapSolver API key
- `requirements.txt` — playwright, httpx

---

## Phase 1 — Multi-Company Worker (v0.2.0) 🔄 IN PROGRESS

**Target tag**: `v0.2.0`  
**Status**: In progress

### Completed

- [x] `src/company_manager.py` — Company CRUD from JSON config
- [x] `config/companies.json` — Sample multi-company configuration
- [x] `src/rate_limiter.py` — Rate limiting between SRI queries (3 min default)
- [x] `src/session_store.py` — Cookie persistence (save/load SRI sessions)
- [x] `src/logger.py` — Structured per-company logging (console + file)
- [x] `src/orchestrator.py` — Multi-company orchestrator entry point

### Pending

- [ ] Proxy rotation integration (iproyal or similar)
- [ ] Session reuse: skip login if cookies are fresh (< 4h)
- [ ] Health check endpoint
- [ ] Download stats per company (total downloaded, last run)
- [ ] Encryption for stored passwords (currently plain text)
- [ ] Integration tests with multiple companies

### Files Changed

- `src/company_manager.py` — Company CRUD (new)
- `src/rate_limiter.py` — Rate limiter (new)
- `src/session_store.py` — Cookie persistence (new)
- `src/logger.py` — Structured logging (new)
- `src/orchestrator.py` — Multi-company orchestrator (new)
- `config/companies.json` — Sample config (new)
- `.gitignore` — Added cookies/ and logs/

---

## Phase 2 — Message Queue Integration (v0.3.0)

**Target tag**: `v0.3.0`  
**Status**: Not started

---

## Phase 3 — MinIO Storage (v0.4.0)

**Target tag**: `v0.4.0`  
**Status**: Not started

---

## Phase 4 — API Gateway (v0.5.0)

**Target tag**: `v0.5.0`  
**Status**: Not started

---

## Phase 5 — Webhooks & ERP Integration (v0.6.0)

**Target tag**: `v0.6.0`  
**Status**: Not started

---

## Phase 6 — Scheduling & Automation (v0.7.0)

**Target tag**: `v0.7.0`  
**Status**: Not started

---

## Phase 7 — Production Hardening (v1.0.0)

**Target tag**: `v1.0.0`  
**Status**: Not started
