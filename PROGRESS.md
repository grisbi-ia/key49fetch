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

## Phase 1 — Multi-Company Worker (v0.2.0) 🔜 NEXT

**Target tag**: `v0.2.0`  
**Status**: Not started

### Planned Work

1. Design `companies` database table (PostgreSQL)
2. Implement company registration (RUC, encrypted SRI password, active flag)
3. Worker loop: iterate companies, download current month, skip already-processed
4. Proxy rotation integration (iproyal or similar)
5. Structured logging per company
6. Rate limiting: minimum 3-minute gap between SRI queries
7. Health check endpoint

### Open Questions

- Database: PostgreSQL (via Quarkus) or SQLite for standalone mode?
- Proxy: residential rotating or datacenter static?
- Worker: single process with async loop or multiple processes?

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
