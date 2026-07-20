# Key49-Fetch — Deployment Guide

## Systemd Service + Timer

The recommended deployment uses systemd for scheduling and process supervision.

### Install

```bash
# 1. Create service user
sudo useradd -r -s /bin/false key49

# 2. Deploy application
sudo mkdir -p /opt/key49-fetch /data/key49-fetch/xml_downloads
sudo cp -r . /opt/key49-fetch/
sudo chown -R key49:key49 /opt/key49-fetch /data/key49-fetch

# 3. Set up Python venv
cd /opt/key49-fetch
sudo -u key49 python3 -m venv .venv
sudo -u key49 .venv/bin/pip install -r requirements.txt
sudo -u key49 .venv/bin/playwright install firefox

# 4. Configure environment
sudo -u key49 cp .env.example .env
sudo -u key49 $EDITOR .env   # Set FERNET_KEY, etc.

# 5. Install systemd units
sudo cp deploy/key49-fetch.service /etc/systemd/system/
sudo cp deploy/key49-fetch.timer /etc/systemd/system/
sudo systemctl daemon-reload

# 6. Enable and start timer
sudo systemctl enable key49-fetch.timer
sudo systemctl start key49-fetch.timer
```

### Operations

```bash
# Check timer status
systemctl status key49-fetch.timer
systemctl list-timers key49-fetch.timer

# Trigger a manual run
sudo systemctl start key49-fetch.service

# View logs
journalctl -u key49-fetch.service -f
journalctl -u key49-fetch.service --since "1 hour ago"

# Run health check
cd /opt/key49-fetch && sudo -u key49 .venv/bin/python -m src.orchestrator --health

# Run for a specific company only
sudo -u key49 .venv/bin/python -m src.orchestrator --companies 0195160252001

# Run for a specific month
sudo -u key49 .venv/bin/python -m src.orchestrator --year 2026 --month 7
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

To change: edit `deploy/key49-fetch.timer` → `OnCalendar=` → copy to `/etc/systemd/system/` → `systemctl daemon-reload`.

### Monitoring

```bash
# Quick health report
python -m src.orchestrator --health

# Check download stats per company
cat /opt/key49-fetch/config/stats.json | python -m json.tool

# Check logs per company
ls /opt/key49-fetch/logs/
tail -f /opt/key49-fetch/logs/0195160252001.log
```

---

## API Gateway (FastAPI)

The REST API can be deployed alongside the download worker.

### Install

```bash
# Add API dependencies
sudo -u key49 /opt/key49-fetch/.venv/bin/pip install fastapi uvicorn

# Create systemd service for the API
sudo cp deploy/key49-fetch-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now key49-fetch-api.service
```

### Configure

```bash
# Set API keys (comma-separated)
echo "API_KEYS=your-secret-key-1,your-secret-key-2" >> /opt/key49-fetch/.env

# Optional: change port
echo "KEY49_API_PORT=8081" >> /opt/key49-fetch/.env
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
    "webhook_url": "https://erp.example.com/api/webhooks/key49",
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
