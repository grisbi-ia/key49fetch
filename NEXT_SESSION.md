# Key49-Fetch — Next Session

> Last updated: 2026-07-17 after Phase 5 (Scheduling & Automation)

---

## What was done

| Phase | Description | Tag |
|-------|-------------|-----|
| 0 | Foundation — SRI downloader script | `v0.1.0` ✅ |
| 1 | Multi-company worker + encryption | `v0.2.0` ✅ |
| 2 | Scheduler + partitioning (no RabbitMQ) | `v0.3.0` ✅ |
| 3 | API Gateway (FastAPI, filesystem-based) | `v0.4.0` ✅ |
| 4 | Webhooks & ERP Integration (HMAC-signed, retry, audit) | `v0.5.0` ✅ |
| 5 | Scheduling & Automation (backfill, alerting, dashboard) | `v0.6.0` ✅ |

---

## What to continue with — Phase 6: Production Hardening (v1.0.0)

**Goal**: Production-ready, monitored, and resilient.

Key tasks:
- [ ] Docker Compose for all services
- [ ] Health checks on all components
- [ ] Prometheus metrics + Grafana dashboard
- [ ] Structured JSON logging (ELK/Loki compatible)
- [ ] Graceful shutdown and restart
- [ ] Load testing (20 companies, concurrent downloads)
- [ ] Disaster recovery: re-download from SRI if data lost
- [ ] Security audit (credential encryption, API key rotation)

---

## Quick reference

```bash
# Run orchestrator (current month)
python -m src.orchestrator

# Run for specific companies
python -m src.orchestrator --companies 0195160252001

# Backfill historical months
python -m src.orchestrator --companies 0195160252001 --backfill 2026-01

# Health check
python -m src.orchestrator --health

# Run API
python -m src.api.app
# Dashboard at http://localhost:8081/

# Run with alerting
ALERT_WEBHOOK_URL=https://hooks.slack.com/... \
ALERT_THRESHOLD=3 \
python -m src.orchestrator
```

---

## Architecture snapshot (v0.6.0)

```
┌──────────────────────────────────────────────────────────────┐
│                     Key49-Fetch v0.6.0                        │
│                                                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐  │
│  │ Scheduler│  │ FastAPI  │  │Orchestr. │  │  Webhooks   │  │
│  │(systemd) │  │ :8081    │  │          │  │  Dispatcher │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬──────┘  │
│       │             │              │                │         │
│       ▼             │              ▼                │         │
│  orchestrator ──────┤─── sri_downloader.py          │         │
│       │             │         │                      │         │
│       │   ┌─────────┘         ▼                      │         │
│       │   │ Dashboard    xml_downloads/              │         │
│       │   │ (HTML+JS)    {ruc}/{month}/{type}/       │         │
│       │   │                    │                     │         │
│       │   │                    └── FileResponse ─────┘         │
│       │   │                                                    │
│       ▼   ▼                                                    │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐   │
│  │companies.json│   │ Alerting     │   │ ERP / Slack /    │   │
│  │ stats.json   │   │ (failure     │──▶│ Telegram         │   │
│  │ webhook      │   │  webhooks)   │   │ (alert receiver) │   │
│  │ audit logs   │   └──────────────┘   └──────────────────┘   │
│  └──────────────┘                                              │
│                                                                 │
│  🆕 Phase 5: backfill, alerting, dashboard                     │
└──────────────────────────────────────────────────────────────┘
```
