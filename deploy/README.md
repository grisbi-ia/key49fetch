# Key49-Fetch — Deployment Guide

## Systemd Service + Timer

The recommended deployment uses systemd for scheduling and process supervision.

### Install

```bash
# 1. Create service user
useradd -r -s /bin/false app

# 2. Deploy application
mkdir -p /opt/app-fetch /data/app-fetch/xml_downloads
cp -r . /opt/app-fetch/
chown -R app:app /opt/app-fetch /data/app-fetch

# 3. Set up Python venv
cd /opt/app-fetch
-u app python3 -m venv .venv
-u app .venv/bin/pip install -r requirements.txt
-u app .venv/bin/playwright install firefox

# 4. Configure environment
-u app cp .env.example .env
-u app $EDITOR .env   # Set FERNET_KEY, etc.

# 5. Install systemd units
cp deploy/app-fetch.service /etc/systemd/system/
cp deploy/app-fetch.timer /etc/systemd/system/
systemctl daemon-reload

# 6. Enable and start timer
systemctl enable app-fetch.timer
systemctl start app-fetch.timer
```

### Operations

```bash
# Check timer status
systemctl status app-fetch.timer
systemctl list-timers app-fetch.timer

# Trigger a manual run
systemctl start app-fetch.service

# View logs
journalctl -u app-fetch.service -f
journalctl -u app-fetch.service --since "1 hour ago"

# Run health check
cd /opt/app-fetch && -u app .venv/bin/python -m src.orchestrator --health

# Run for a specific company only
-u app .venv/bin/python -m src.orchestrator --companies 0195160252001

# Run for a specific month
-u app .venv/bin/python -m src.orchestrator --year 2026 --month 7
```

### Horizontal Scaling (Multiple Instances)

Deploy additional instances, each handling a subset of RUCs:

```bash
# Instance 1 - handles first batch of RUCs
# .env:
COMPANY_FILTER=0195160252001,0992156406001

# Instance 2 - handles second batch of RUCs
# .env:
COMPANY_FILTER=1790012345001,0990012345001
```

Each instance runs its own systemd timer independently. No coordination needed
because:
- Each instance only queries its assigned RUCs
- `rate_limiter` applies per-instance SRI delays
- Skip-existing-files prevents duplicate downloads across instances

### Timer Schedule

Default: every 6 hours (00:15, 06:15, 12:15, 18:15) with ±5 min randomization.

To change: edit `deploy/app-fetch.timer` → `OnCalendar=` → copy to `/etc/systemd/system/` → `systemctl daemon-reload`.

### Monitoring

```bash
# Quick health report
python -m src.orchestrator --health

# Check download stats per company
cat /opt/app-fetch/config/stats.json | python -m json.tool

# Check logs per company
ls /opt/app-fetch/logs/
tail -f /opt/app-fetch/logs/0195160252001.log
```

---

## API Gateway (FastAPI)

The REST API can be deployed alongside the download worker.

### Install

```bash
# Add API dependencies
-u app /opt/app-fetch/.venv/bin/pip install fastapi uvicorn

# Create systemd service for the API
cp deploy/app-fetch-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now app-fetch-api.service
```

### Configure

```bash
# Set API keys (comma-separated)
echo "API_KEYS=your-secret-key-1,your-secret-key-2" >> /opt/app-fetch/.env

# Optional: change port
echo "KEY49_API_PORT=8081" >> /opt/app-fetch/.env
```

### API Endpoints

```
GET  /api/v1/health                           Health check
GET  /api/v1/companies                         List companies
GET  /api/v1/documents?company_id=X&year=Y     List documents (paginated)
                       &month=M&type=T
GET  /api/v1/documents/{access_key}?           Download file (xml/pdf)
     company_id=X&year=Y&month=M&type=T
                       &format=xml|pdf
```

### Test

```bash
curl http://localhost:8081/api/v1/health
curl -H "X-API-Key: your-secret-key-1" \
  "http://localhost:8081/api/v1/documents?company_id=0195160252001&year=2026&month=4"
```

Swagger docs available at `http://localhost:8081/docs` (set `ENABLE_DOCS=0` to disable).

---

## Webhook Configuration (ERP Integration)

Add webhook per company in `config/companies.json`:

```json
{
    "company_id": "0195160252001",
    "ruc": "0195160252001",
    "business_name": "AuraCore Systems",
    "sri_password_encrypted": "...",
    "is_active": true,
    "download_types": [1, 6],
    "schedule": "daily",
    "proxy_profile": null,
    "webhook_url": "https://erp.example.com/api/webhooks/app",
    "webhook_secret": "your-hmac-secret-here"
}
```

### How it works

1. After each successful download with `new_documents > 0`, the orchestrator sends:
   ```
   POST {webhook_url}
   Content-Type: application/json
   X-Key49-Signature: HMAC-SHA256(body, webhook_secret)
   X-Key49-Event: documents.downloaded

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

2. Retries: up to 3 attempts with exponential backoff (2s, 4s, 8s)
3. Audit: all deliveries logged to `logs/webhooks/{company_id}.jsonl`

### Verify signature (Python example for ERP receiver)

```python
import hashlib
import hmac
import json

def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

### Test with a local echo server

```bash
python -c "
from aiohttp import web
async def handler(request):
    body = await request.json()
    print('Webhook received:', json.dumps(body, indent=2))
    return web.json_response({'status': 'ok'})
app = web.Application()
app.router.add_post('/webhook', handler)
web.run_app(app, port=9999)
"
```
