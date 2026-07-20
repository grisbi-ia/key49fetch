# Key49-Fetch — Development Roadmap

## Phase 0 — Foundation (v0.1.0) ✅ DONE

**Goal**: Standalone script capable of downloading SRI documents for a single company.

- [x] Python script `sri_downloader.py` with Playwright + Firefox
- [x] SRI login automation
- [x] reCAPTCHA bypass (native trust scoring + human-like behavior)
- [x] Multi-type download (Facturas, Retenciones, Notas de Crédito, etc.)
- [x] Skip already-downloaded files
- [x] Auto-retry with exponential backoff
- [x] Menu-based navigation (human-like browsing)
- [x] Playwright-based human clicks (mouse movement, scroll, delays)
- [x] Output structure: `{ruc}/{month}/{type}/`

**Tag**: `v0.1.0`

---

## Phase 1 — Multi-Company Worker (v0.2.0) ✅ DONE

**Goal**: Convert standalone script into a multi-company worker service.

- [x] Configuration file for multiple companies (`config/companies.json`)
- [x] Company CRUD management (RUC, SRI credentials, active status)
- [x] Credential encryption at rest (Fernet AES-128-CBC via `FERNET_KEY`)
- [x] Session persistence (save/load SRI cookies, 4h validity)
- [x] Rate limiting between SRI queries (3 min default, configurable)
- [x] Download statistics per company (`config/stats.json`)
- [x] Structured per-company logging (console + file)
- [x] Health check via `--health` CLI flag
- [x] Password override via env var `SRI_PASSWORD_{RUC}`

**Tag**: `v0.2.0`

---

## Phase 2 — Scheduler & Partitioning (v0.3.0) ✅ DONE

**Goal**: Schedule periodic downloads and support horizontal scaling via RUC partitioning.

- [x] `download_xmls()` returns structured result dict (status + counts)
- [x] Orchestrator captures real download counts (not hardcoded zeros)
- [x] `--companies` CLI flag for comma-separated company IDs
- [x] `COMPANY_FILTER` env var for instance-level partitioning
- [x] Systemd service + timer units (every 6h, ±5 min jitter)
- [x] Deployment guide (`deploy/README.md`)

**Architecture decision**: RabbitMQ deferred to Phase 4 (API Gateway).
Current workload is deterministic — no need for a message broker yet.
Horizontal scaling = deploy another instance with different `COMPANY_FILTER`.

**Tag**: `v0.3.0`

---

## Phase 3 — API Gateway (v0.4.0) ✅ DONE

**Goal**: Expose documents via REST API for ERP/web consumption, served directly from filesystem.

- [x] FastAPI application (`src/api/app.py`)
- [x] API key authentication via `X-API-Key` header (`src/api/auth.py`)
- [x] Document scanner with SRI access key metadata extraction (`src/api/documents.py`)
- [x] `GET /api/v1/health` — Health check
- [x] `GET /api/v1/companies` — List registered companies
- [x] `GET /api/v1/documents?company_id=X&year=Y&month=M&type=T` — List documents with pagination
- [x] `GET /api/v1/documents/{access_key}?company_id=X&...&format=xml|pdf` — Download single file
- [x] `.env.example` with all configuration options
- [x] API docs via Swagger UI (`/docs`)

**Architecture decision**: Files stored on local filesystem, served via FastAPI `FileResponse`.
MinIO deferred — not needed for current scale (single-node, fixed workload).
Signed URLs can be implemented in the API layer if needed later.

**Tag**: `v0.4.0`

---

## Phase 4 — Webhooks & ERP Integration (v0.5.0) ✅ DONE

**Goal**: Push notifications to ERPs when new documents arrive.

- [x] Configurable webhook URL + secret per company (in `companies.json`)
- [x] Webhook payload: `{event, company_id, ruc, period, new_documents, total_documents, timestamp}`
- [x] HMAC-SHA256 signature in `X-Key49-Signature` header
- [x] Retry failed webhooks (3 attempts, exponential backoff: 2s, 4s, 8s)
- [x] JSONL audit trail per company: `logs/webhooks/{company_id}.jsonl`
- [x] ERP integration flow: webhook notifies → ERP calls API for details

**Tag**: `v0.5.0`

---

## Phase 5 — Scheduling & Automation (v0.6.0) ✅ DONE

**Goal**: Fully automated periodic downloads with backfill, failure alerting, and dashboard.

- [x] Historical backfill mode: `--backfill YYYY-MM` downloads all months from start to now
- [x] Consecutive failure tracking in stats (`consecutive_failures`, `last_error`)
- [x] Alert webhook when failures exceed threshold (configurable via `ALERT_WEBHOOK_URL`, `ALERT_THRESHOLD`)
- [x] Alert payload: `{event, company_id, ruc, consecutive_failures, threshold, last_error, severity}`
- [x] Web dashboard at `/` and `/dashboard` — company cards with status, doc counts, failure alerts
- [x] Auto-refresh every 30s on dashboard
- [x] Per-company schedule config already in `companies.json` (Phase 1)
- [x] Incremental downloads via skip-existing (Phase 0)

**Architecture note**: Scheduling is handled by systemd timer (Phase 2).
Phase 5 adds operational features: backfill for onboarding, alerting for failures,
and dashboard for monitoring.

**Tag**: `v0.6.0`

---

## Phase 6 — Web Admin Interface (v0.7.0)

**Goal**: Web-based administration panel to manage companies and trigger downloads.

- [ ] `POST /api/v1/companies` — Add/register new company via API
- [ ] `PUT /api/v1/companies/{id}` — Edit company (RUC, password, types, webhook)
- [ ] `DELETE /api/v1/companies/{id}` — Deactivate company
- [ ] `POST /api/v1/fetch` — Trigger download for a specific company/month
- [ ] Admin UI at `/admin` — Forms for company CRUD, download triggers, backfill
- [ ] Auth separation: admin panel uses separate admin API key
- [ ] Activity log: who triggered what and when

**Tag**: `v0.7.0`

---

## Phase 7 — Production Hardening (v1.0.0)

**Goal**: Production-ready, monitored, and resilient.

- [ ] Docker Compose for all services
- [ ] Health checks on all components
- [ ] Prometheus metrics + Grafana dashboard
- [ ] Structured JSON logging (ELK/Loki compatible)
- [ ] Graceful shutdown and restart
- [ ] Load testing (20 companies, concurrent downloads)
- [ ] Disaster recovery: re-download from SRI if MinIO data lost
- [ ] Security audit (credential encryption, API key rotation)

**Tag**: `v1.0.0`
