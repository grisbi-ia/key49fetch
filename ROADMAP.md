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

## Phase 2 — Message Queue Integration (v0.3.0)

**Goal**: Decouple job submission from execution via RabbitMQ.

- [ ] RabbitMQ exchange setup (`key49.fetch`, type topic)
- [ ] Queue `key49.fetch.jobs` (job ingestion)
- [ ] Queue `key49.fetch.results` (result publication)
- [ ] Job DTO: `{job_id, company_id, ruc, password, year, month, types, known_keys}`
- [ ] Result DTO: `{job_id, status, documents[], errors[], summary}`
- [ ] Worker consumes jobs, publishes results
- [ ] Job retry + dead-letter queue
- [ ] Idempotency: same job twice = no duplicate downloads

**Tag**: `v0.3.0`

---

## Phase 3 — MinIO Storage (v0.4.0)

**Goal**: Store documents in object storage instead of local disk.

- [ ] MinIO client integration (boto3 or minio-py)
- [ ] Bucket structure: `{bucket}/{company_id}/{year}-{month:02d}/{type:02d}/`
- [ ] Upload XMLs and PDFs after download
- [ ] Signed URL generation for external access
- [ ] Local temp folder cleanup after upload
- [ ] Configurable: MinIO endpoint, access key, secret key, bucket
- [ ] Fallback to local storage if MinIO unreachable

**Tag**: `v0.4.0`

---

## Phase 4 — API Gateway (v0.5.0)

**Goal**: Expose documents via REST API for ERP consumption.

- [ ] REST API (FastAPI or Quarkus)
- [ ] `GET /api/v1/companies` — List registered companies
- [ ] `POST /api/v1/companies` — Register new company
- [ ] `GET /api/v1/documents?company_id=X&year=Y&month=M&type=T` — List documents
- [ ] `GET /api/v1/documents/{id}/download` — Download single document (signed URL)
- [ ] API key authentication
- [ ] Rate limiting per API consumer
- [ ] Pagination on list endpoints

**Tag**: `v0.5.0`

---

## Phase 5 — Webhooks & ERP Integration (v0.6.0)

**Goal**: Push notifications to ERPs when new documents arrive.

- [ ] Configurable webhook URL per company
- [ ] Webhook payload: `{company_id, month, new_documents[], timestamp}`
- [ ] Retry failed webhooks (3 attempts, exponential backoff)
- [ ] Webhook secret for HMAC signature verification
- [ ] ERP adapters (Odoo, SAP, custom REST)
- [ ] Webhook event log / audit trail

**Tag**: `v0.6.0`

---

## Phase 6 — Scheduling & Automation (v0.7.0)

**Goal**: Fully automated periodic downloads without human intervention.

- [ ] Cron-based scheduler (or `@Scheduled` in Quarkus)
- [ ] Per-company schedule config (daily, weekly, custom)
- [ ] Current-month incremental downloads (only new documents)
- [ ] Historical backfill mode (download past months on first registration)
- [ ] Alerting on repeated failures (Slack/Telegram webhook or email)
- [ ] Dashboard: company status, last download, document counts

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
