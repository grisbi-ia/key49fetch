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

## Phase 1 — Multi-Company Worker (v0.2.0) ✅ COMPLETED

**Tag**: `v0.2.0`  
**Completed**: 2026-07-17

### Completed

- [x] `src/company_manager.py` — Company CRUD from JSON config (with encryption)
- [x] `src/crypto.py` — AES-128-CBC credential encryption (Fernet)
- [x] `config/companies.json` — Sample multi-company configuration
- [x] `src/rate_limiter.py` — Rate limiting between SRI queries (3 min default)
- [x] `src/session_store.py` — Cookie persistence (save/load SRI sessions)
- [x] `src/stats_tracker.py` — Download statistics per company
- [x] `src/logger.py` — Structured per-company logging (console + file)
- [x] `src/orchestrator.py` — Multi-company orchestrator with health check
- [x] `--health` CLI flag for operational monitoring
- [x] Session reuse detection (logs whether valid cookies exist)
- [x] Credential encryption at rest (Fernet key from `FERNET_KEY` env var)

### Files Changed

- `src/company_manager.py` — Company CRUD with encryption (new)
- `src/crypto.py` — Fernet encryption utilities (new)
- `src/rate_limiter.py` — Rate limiter (new)
- `src/session_store.py` — Cookie persistence (new)
- `src/stats_tracker.py` — Download statistics (new)
- `src/logger.py` — Structured logging (new)
- `src/orchestrator.py` — Multi-company orchestrator (new)
- `config/companies.json` — Sample config (new)
- `requirements.txt` — Added `cryptography>=41.0`
- `.gitignore` — Added cookies/ and logs/

---

## Phase 2 — Scheduler & Partitioning (v0.3.0) ✅ COMPLETED

**Tag**: `v0.3.0`  
**Completed**: 2026-07-17

### Summary

Simplified Phase 2 — replaced RabbitMQ with a pragmatic scheduler + partitioning approach. No new infrastructure dependencies. Horizontal scaling achieved by deploying multiple instances, each with a subset of RUCs.

### Completed

- [x] `download_xmls()` returns structured result dict (status, downloaded, skipped, errors)
- [x] Orchestrator captures real download counts (was hardcoded to 0)
- [x] `--companies` CLI flag accepts comma-separated company IDs
- [x] `COMPANY_FILTER` env var for instance-level RUC partitioning
- [x] Systemd service unit (`deploy/key49-fetch.service`)
- [x] Systemd timer unit (`deploy/key49-fetch.timer`) — every 6h with jitter
- [x] Deployment guide (`deploy/README.md`)
- [x] `NEXT_SESSION.md` created

### Architecture Decision

**Replaced**: RabbitMQ exchange + queues + DTOs + DLQ  
**With**: Systemd timer + `COMPANY_FILTER` partitioning + idempotent skip-existing

Rationale:
- Workload is deterministic (X fixed RUCs × Y fixed document types)
- Skip-existing-files already guarantees idempotency
- Horizontal scaling = deploy another instance with different `COMPANY_FILTER`
- Rate limiting is per-instance (no coordination needed)
- RabbitMQ will be added in Phase 4 when API Gateway requires async job dispatch

### Files Changed

- `sri_downloader.py` — `download_xmls()` now returns result dict
- `src/orchestrator.py` — Multi-company filter, uses returned counts, `COMPANY_FILTER` env var
- `deploy/key49-fetch.service` — Systemd unit (new)
- `deploy/key49-fetch.timer` — Systemd timer (new)
- `deploy/README.md` — Deployment guide (new)
- `NEXT_SESSION.md` — Created

---

## Phase 3 — API Gateway (v0.4.0) ✅ COMPLETED

**Tag**: `v0.4.0`  
**Completed**: 2026-07-17

### Summary

FastAPI REST API serving documents directly from the filesystem. No MinIO needed — files are served via `FileResponse` from the existing `xml_downloads` directory structure. API key authentication, paginated document listing with SRI access key metadata extraction, and direct file downloads.

### Completed

- [x] `src/api/app.py` — FastAPI application with all endpoints
- [x] `src/api/auth.py` — API key auth via `X-API-Key` header, dev mode when no keys configured
- [x] `src/api/documents.py` — Filesystem scanner + SRI access key metadata parser
- [x] `src/api/companies.py` — Company listing from companies.json + stats
- [x] `GET /api/v1/health` — Health check
- [x] `GET /api/v1/companies` — List companies with stats
- [x] `GET /api/v1/documents` — Paginated document listing with filters
- [x] `GET /api/v1/documents/{access_key}` — File download (xml/pdf) with Content-Type headers
- [x] Swagger UI at `/docs` (configurable via `ENABLE_DOCS` env var)
- [x] `.env.example` — Complete configuration reference

### Architecture Decision

**MinIO skipped** — Files served directly from filesystem via FastAPI `FileResponse`.
Rationale:
- Single-node deployment, no need for S3-compatible object storage
- `FileResponse` is zero-copy and more efficient for local files
- No additional infrastructure (MinIO server, bucket config, SDK)
- Signed URLs can be added at the API layer if needed (HMAC-signed redirects)
- Revisit MinIO only if: multi-node API, very large files (GB), or Key49 Quarkus already uses MinIO and wants unified storage

### Endpoints

```
GET /api/v1/health
GET /api/v1/companies                          → list all companies
GET /api/v1/documents?company_id=X&year=Y&month=M&type=T&page=1&page_size=50
GET /api/v1/documents/{access_key}?company_id=X&year=Y&month=M&type=T&format=xml|pdf
```

### Files Changed

- `src/api/__init__.py` — Package init (new)
- `src/api/app.py` — FastAPI app (new)
- `src/api/auth.py` — API key authentication (new)
- `src/api/documents.py` — Document scanner + access key parser (new)
- `src/api/companies.py` — Company listing (new)
- `requirements.txt` — Added `fastapi`, `uvicorn`
- `.env.example` — Configuration reference (new)

---

## Phase 4 — Webhooks & ERP Integration (v0.5.0) ✅ COMPLETED

**Tag**: `v0.5.0`  
**Completed**: 2026-07-17

### Summary

Webhook notifications push to ERPs when new documents are downloaded. HMAC-SHA256 signed payloads, automatic retry with exponential backoff, and JSONL audit trail per company.

### Completed

- [x] `src/webhooks/dispatcher.py` — HMAC-signed webhook delivery with retry (3 attempts, 2s/4s/8s backoff)
- [x] `src/webhooks/__init__.py` — Package
- [x] `CompanyConfig` extended with `webhook_url` and `webhook_secret` fields
- [x] `config/companies.json` — Example webhook fields
- [x] Orchestrator dispatches webhook after successful download (only if new_documents > 0)
- [x] Audit log per company: `logs/webhooks/{company_id}.jsonl`
- [x] `.gitignore` updated for webhook audit logs

### Webhook Payload

```json
{
  "event": "documents.downloaded",
  "company_id": "0195160252001",
  "ruc": "0195160252001",
  "period": "2026-07",
  "new_documents": 3,
  "total_documents": 53,
  "timestamp": "2026-07-17T22:00:00Z"
}
```

Headers:
- `X-Key49-Signature: HMAC-SHA256(body, secret)`
- `X-Key49-Event: documents.downloaded`

### ERP Integration Flow

```
Orchestrator
    │
    ├── download_xmls() → {downloaded: 3, skipped: 50}
    │
    ├── if webhook_url and downloaded > 0:
    │       dispatch_webhook(url, secret, ...)
    │           ├── POST with HMAC signature
    │           ├── Retry up to 3 times
    │           └── Log to logs/webhooks/{company_id}.jsonl
    │
    └── ERP receives webhook → calls GET /api/v1/documents for details
```

### Files Changed

- `src/webhooks/__init__.py` — Package init (new)
- `src/webhooks/dispatcher.py` — Webhook dispatcher (new)
- `src/company_manager.py` — Added `webhook_url`, `webhook_secret` fields
- `src/orchestrator.py` — Webhook dispatch after download
- `config/companies.json` — Webhook field examples
- `.env.example` — Webhook config docs
- `.gitignore` — Added `logs/webhooks/`

---

## Phase 5 — Scheduling & Automation (v0.6.0) ✅ COMPLETED

**Tag**: `v0.6.0`  
**Completed**: 2026-07-17

### Summary

Operational features for production use: historical backfill for onboarding new companies, failure alerting via webhooks, and a live monitoring dashboard. Scheduling itself is handled by systemd timer (Phase 2).

### Completed

- [x] `--backfill YYYY-MM` CLI flag — downloads all months from start to current
- [x] `orchestrator.backfill()` method iterates month-by-month with full stats
- [x] `src/stats_tracker.py` — Added `consecutive_failures` and `last_error` tracking
- [x] `src/alerting.py` — Failure alert dispatcher (webhook with HMAC signature)
- [x] Alert threshold configurable via `ALERT_THRESHOLD` (default: 3 consecutive failures)
- [x] Alert webhook URL via `ALERT_WEBHOOK_URL` env var
- [x] Orchestrator records failures and triggers alerts at threshold
- [x] `src/api/templates/dashboard.html` — Live monitoring dashboard
- [x] Dashboard endpoints: `GET /` and `GET /dashboard`
- [x] Dashboard shows: company cards, doc counts, status dots, failure alerts, auto-refresh
- [x] `/api/v1/companies` now returns `consecutive_failures` and `last_error`

### New CLI Commands

```bash
# Backfill: download Jan-Jul for a specific company
python -m src.orchestrator --companies 0195160252001 --backfill 2026-01

# Alerting: configure env vars
ALERT_WEBHOOK_URL=https://hooks.slack.com/...  # or Telegram bot URL
ALERT_THRESHOLD=3  # alert after 3 consecutive failures
```

### Files Changed

- `src/orchestrator.py` — Added `backfill()` method, `_check_and_alert()`, `--backfill` flag
- `src/stats_tracker.py` — Added `consecutive_failures`, `last_error`, `record_failure()`
- `src/alerting.py` — Failure alert dispatcher (new)
- `src/api/app.py` — Dashboard endpoint, version bumped to 0.6.0
- `src/api/companies.py` — Returns `consecutive_failures`, `last_error`
- `src/api/templates/dashboard.html` — Dashboard HTML (new)

---

## Phase 6 — Web Admin Interface (v0.7.0)

**Target tag**: `v0.7.0`  
**Status**: Not started

---

## Phase 7 — Production Hardening (v1.0.0)

**Target tag**: `v1.0.0`  
**Status**: Not started
