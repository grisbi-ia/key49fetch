# Key49-Fetch — Guía de Despliegue

> Probado en producción — Julio 2026 | Versión: v0.6.0

---

## 1. Requisitos

- Linux (Ubuntu/Debian)
- Python 3.9+
- Git
- Acceso a `github.com` (repositorio privado) y `srienlinea.sri.gob.ec`
- **IP residencial ecuatoriana** (datacenter IPs como Contabo/Hetzner son bloqueadas por el SRI)
- **Todo se ejecuta como `root`**

---

## 2. Configurar acceso SSH a GitHub

El repositorio es privado. Hay que generar una llave SSH y agregarla como **deploy key**.

```bash
# Generar llave (solo una vez)
ssh-keygen -t ed25519 -C "key49-fetch-server" -f ~/.ssh/id_ed25519 -N ""

# Mostrar llave pública (copiar todo el contenido)
cat ~/.ssh/id_ed25519.pub
```

1. Ir a: `https://github.com/grisbi-ia/key49fetch/settings/keys`
2. **Add deploy key** → título: `servidor` → pegar la llave → ✅ Allow write access → **Add key**
3. Verificar: `ssh -T git@github.com` (debe responder "Hi grisbi-ia...")

---

## 3. Instalación

```bash
# Clonar
cd /opt
git clone git@github.com:grisbi-ia/key49fetch.git
cd key49-fetch

# Entorno virtual
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Dependencias del sistema para Firefox
apt-get install -y libxcb-shm0 libx11-xcb1 libxrandr2 libxcomposite1 \
    libxcursor1 libxdamage1 libxi6 libxfixes3 libgtk-3-0 \
    libpangocairo-1.0-0 libpango-1.0-0 libatk1.0-0 \
    libcairo-gobject2 libcairo2 libgdk-pixbuf-2.0-0 \
    libxrender1 libasound2

# Instalar Firefox para Playwright
.venv/bin/playwright install firefox
```

---

## 4. Configurar .env

```bash
cd /opt/key49-fetch

# Generar llave de encriptación para contraseñas SRI
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Copiar el resultado

# Crear .env
cat > .env <<EOF
FERNET_KEY=LA_CLAVE_GENERADA_ARRIBA
KEY49_API_PORT=8081
KEY49_OUTPUT_DIR=/data/key49-fetch/xml_downloads
ENABLE_DOCS=1
EOF
```

> ⚠️ Sin `FERNET_KEY`, las contraseñas SRI se guardan en texto plano. Guarda esta clave en un lugar seguro.

---

## 5. Registrar empresas

```bash
nano config/companies.json
```

```json
[
    {
        "company_id": "0190411826001",
        "ruc": "0190411826001",
        "business_name": "Mi Empresa SA",
        "sri_password_encrypted": "CLAVE_DEL_SRI",
        "is_active": true,
        "download_types": [1, 6],
        "schedule": "daily",
        "proxy_profile": null,
        "webhook_url": null,
        "webhook_secret": null
    }
]
```

| Campo | Notas |
|-------|-------|
| `ruc` | 10 dígitos (cédula) o 13 (RUC). Si pones 10, se auto-completa a 13 |
| `download_types` | 1=Factura, 2=Liquidación, 3=NC, 4=ND, 6=Retención |
| `webhook_url` | Opcional. URL donde notificar documentos nuevos |

> Para agregar/quitar empresas **no hay que reiniciar nada**. Se lee del archivo en cada ejecución.

---

## 6. Instalar servicios systemd

```bash
cp deploy/key49-fetch-api.service /etc/systemd/system/
cp deploy/key49-fetch.service /etc/systemd/system/
cp deploy/key49-fetch.timer /etc/systemd/system/
systemctl daemon-reload
```

---

## 7. Arrancar

```bash
# API Gateway (siempre corriendo)
systemctl enable --now key49-fetch-api.service

# Timer de descargas (cada 6 horas: 00:15, 06:15, 12:15, 18:15)
systemctl enable --now key49-fetch.timer
```

Verificar:

```bash
systemctl status key49-fetch-api.service    # active (running)
systemctl status key49-fetch.timer          # active (waiting)
curl -s http://localhost:8081/api/v1/health # {"status":"ok"}
```

---

## 8. Primera descarga (manual)

> Las descargas **no** son automáticas al registrar una empresa. Hay que dispararlas manualmente.

```bash
# Disparar descarga del mes corriente
curl -X POST "http://localhost:8081/api/v1/fetch?company_id=0190411826001"

# Ver estado del job
curl "http://localhost:8081/api/v1/fetch"

# Listar documentos descargados
curl "http://localhost:8081/api/v1/documents?company_id=0190411826001&year=2026&month=7"

# Backfill (varios meses de una vez, vía CLI):
cd /opt/key49-fetch
.venv/bin/python -m src.orchestrator --companies 0190411826001 --backfill 2026-01
```

---

## 9. Actualizar

```bash
cd /opt/key49-fetch
git pull origin master
.venv/bin/pip install -q -r requirements.txt
systemctl restart key49-fetch-api.service
```

---

## 10. Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/` | Dashboard web |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/api/v1/health` | Health check |
| `GET` | `/api/v1/companies` | Lista empresas |
| `GET` | `/api/v1/documents?company_id=X&year=Y&month=M` | Lista documentos |
| `GET` | `/api/v1/documents/{clave}?company_id=X&...&format=xml\|pdf` | Descarga archivo |
| `POST` | `/api/v1/fetch?company_id=X` | Dispara descarga |
| `GET` | `/api/v1/fetch/{job_id}` | Estado del job |
| `GET` | `/api/v1/fetch` | Lista jobs recientes |

---

## 11. Troubleshooting

| Error | Causa | Solución |
|-------|-------|----------|
| `status=226/NAMESPACE` | Restricciones systemd | `git pull` (ya corregido) |
| `Failed to load environment files` | Falta `.env` | Crear `.env` con `FERNET_KEY` (sección 4) |
| `status=203/EXEC` | No existe `.venv` | Crear venv e instalar deps (sección 3) |
| `missing dependencies to run browsers` | Faltan libs del sistema | `apt-get install` librerías (sección 3) |
| `git@github.com: Permission denied` | Sin llave SSH | Configurar deploy key (sección 2) |
| API no arranca / puerto ocupado | Conflicto | Cambiar `KEY49_API_PORT` en `.env` |

---

## 12. Monitoreo

```bash
# Dashboard: http://IP-DEL-SERVIDOR:8081/
# Health: curl http://localhost:8081/api/v1/health
# Logs: journalctl -u key49-fetch-api.service -f
# Stats: cat /opt/key49-fetch/config/stats.json | python3 -m json.tool
# Webhooks: cat /opt/key49-fetch/logs/webhooks/*.jsonl
```
