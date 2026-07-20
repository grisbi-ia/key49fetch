# Key49-Fetch — Next Session

> Last updated: 2026-07-20 after deployment testing on Contabo

---

## State of the project (v0.6.0)

| Phase | Description | Tag | Status |
|-------|-------------|-----|--------|
| 0 | Foundation — SRI downloader | `v0.1.0` | ✅ |
| 1 | Multi-company worker + encryption | `v0.2.0` | ✅ |
| 2 | Scheduler + partitioning | `v0.3.0` | ✅ |
| 3 | API Gateway (FastAPI) | `v0.4.0` | ✅ |
| 4 | Webhooks & ERP integration | `v0.5.0` | ✅ |
| 5 | Backfill, alerting, dashboard | `v0.6.0` | ✅ |
| 6 | Web Admin Interface | `v0.7.0` | ⬜ |
| 7 | Production Hardening | `v1.0.0` | ⬜ |

---

## Deployment learnings (2026-07-20)

### What works
- ✅ Systemd deployment on Linux (Ubuntu/Debian)
- ✅ FastAPI serving on port 8081
- ✅ Dashboard (`/`), Swagger (`/docs`), Health endpoint
- ✅ POST `/api/v1/fetch` triggers background download
- ✅ SSH deploy keys for private GitHub repos
- ✅ Firefox + Playwright installed and running as root
- ✅ SRI login works (RUC + password, Keycloak, reCAPTCHA)

### What we learned
- ⚠️ **Datacenter IPs (Contabo) are problematic**: SRI Keycloak redirects hang or fail on non-residential IPs, causing account lockout after 5 failed attempts
- ✅ **Fix**: Run on an Ecuadorian residential IP (local server, proxy, or Ecuador-based VPS)
- ✅ Systemd needs `HOME=/root` and `XDG_RUNTIME_DIR=/run/user/0` for Firefox as root
- ✅ `MemoryMax=256M` is too low for Firefox — use 2G minimum
- ✅ `PYTHONUNBUFFERED=1` enables real-time log output
- ✅ `.env` with `FERNET_KEY` is mandatory before starting services
- ✅ RUCs accept 10-digit cédulas (auto-padded to 13 with `001`)

### Reverted changes (Contabo-specific, not needed on clean IPs)
- Navigation via `GeneraToken.jsp` → restored to original perfil → redireccion=57 flow
- Post-login redirect skipping → restored to standard `networkidle` + human_delay

---

## Next: deploy on Ecuador IP

### Steps
1. Recover SRI password (locked after Contabo tests)
2. Set up server with Ecuadorian IP
3. Follow `DEPLOY.md` or run `install.sh`
4. `POST /api/v1/fetch?company_id=X` for each RUC
5. Verify documents appear in `/data/key49-fetch/xml_downloads`

### Quick deploy
```bash
# On Ecuador IP server, as root:
cd /opt
git clone git@github.com:grisbi-ia/key49fetch.git
cd key49-fetch
./install.sh

# Edit companies, trigger first download:
nano config/companies.json
curl -X POST "http://localhost:8081/api/v1/fetch?company_id=TU_RUC"
```

---

## Future: Phase 6 — Web Admin Interface (v0.7.0)

- Form-based company CRUD (add/edit/delete via web UI)
- Download trigger button per company
- Backfill with date picker
- Activity log
