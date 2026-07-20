# Key49-Fetch — Guía de Despliegue y Primeros RUCs

> Última actualización: 2026-07-17 | Versión: v0.6.0

---

## 1. Requisitos del servidor

| Componente | Mínimo |
|-----------|--------|
| OS | Linux (Ubuntu 22.04+ recomendado) |
| RAM | 2 GB (Firefox headless ~500 MB por ejecución) |
| Disco | 5 GB |
| Python | 3.10+ |
| Red | Acceso a `srienlinea.sri.gob.ec` |

---

## 2. Instalación rápida (script automático)

Como **root**, copia y ejecuta el script:

```bash
# En tu servidor, como root:
curl -O https://raw.githubusercontent.com/grisbi-ia/key49fetch/master/install.sh
chmod +x install.sh
./install.sh
```

El script hace todo: crea usuario `app`, clona repo, instala dependencias, configura systemd, y arranca la API.

Saltar a [sección 5](#5-primera-descarga-bajo-demanda) para la primera descarga.

### 2.1. Alternativa: subir sin Git (tar.gz)

Si el servidor no tiene Git o no quieres clonar el repo:

**En tu máquina local:**

```bash
cd /ruta/a/key49fetch

# Excluir lo que no se necesita en producción
tar -czf key49fetch.tar.gz \
    --exclude='.venv' \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='bot_descargas_v2' \
    --exclude='*.tar.gz' \
    --exclude='xml_downloads' \
    --exclude='logs' \
    --exclude='cookies' \
    .

# Subir al servidor (el método que prefieras):
scp key49fetch.tar.gz root@TU_SERVIDOR:/opt/
```

**En el servidor, como root:**

```bash
cd /opt
tar -xzf key49fetch.tar.gz -C key49fetch
cd key49fetch

# Crear usuario de servicio
useradd -r -s /bin/false app 2>/dev/null || true

# Crear directorio de datos
mkdir -p /data/key49-fetch/xml_downloads

# Entorno virtual
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install firefox

# Generar FERNET_KEY
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Copiar el resultado y crear .env (ver sección 4)

# Permisos
chown -R app:app /opt/key49-fetch /data/key49-fetch

# Instalar servicios
cp deploy/key49-fetch.service /etc/systemd/system/
cp deploy/key49-fetch.timer /etc/systemd/system/
cp deploy/key49-fetch-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now key49-fetch-api.service
systemctl enable --now key49-fetch.timer
```

---

## 3. Instalación manual (paso a paso)

Si prefieres control total, sigue estos pasos como **root**:

```bash
# ─── 3.1. Crear usuario de servicio ────────────────────────────
useradd -r -s /bin/false app

# ─── 3.2. Crear directorios ────────────────────────────────────
mkdir -p /opt/key49-fetch /data/key49-fetch/xml_downloads

# ─── 3.3. Clonar repositorio ──────────────────────────────────
cd /opt
git clone git@github.com:grisbi-ia/key49fetch.git
cd key49-fetch

# ─── 3.4. Entorno virtual ──────────────────────────────────────
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# ─── 3.5. Instalar Firefox para Playwright ────────────────────
.venv/bin/playwright install firefox
# Si falla por dependencias del sistema:
# .venv/bin/playwright install-deps firefox
# .venv/bin/playwright install firefox

# ─── 3.6. Permisos ─────────────────────────────────────────────
chown -R app:app /opt/key49-fetch /data/key49-fetch
```

---

## 4. Configuración

```bash
# ─── 4.1. Generar FERNET_KEY ──────────────────────────────────
cd /opt/key49-fetch
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Copiar el resultado ↓

# ─── 4.2. Crear .env ───────────────────────────────────────────
cat > .env <<EOF
FERNET_KEY=la-clave-generada-arriba
KEY49_API_PORT=8081
KEY49_OUTPUT_DIR=/data/key49-fetch/xml_downloads
ENABLE_DOCS=1
# API_KEYS=clave-api-1,clave-api-2
# ALERT_WEBHOOK_URL=https://hooks.slack.com/...
# ALERT_THRESHOLD=3
EOF

# ─── 4.3. Registrar RUCs ──────────────────────────────────────
nano config/companies.json
```

### Formato de companies.json

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

### Tipos de documento (`download_types`)

| Código | Nombre |
|--------|--------|
| 1 | Factura |
| 2 | Liquidación de compra |
| 3 | Notas de Crédito |
| 4 | Notas de Débito |
| 6 | Comprobante de Retención |

---

## 5. Primera descarga (bajo demanda)

> ⚠️ Registrar un RUC NO dispara descargas automáticas.
> La primera descarga debe solicitarse manualmente vía API o CLI.

### 5.1. Vía API (recomendado)

```bash
# Asegúrate que la API esté corriendo (ver sección 7)
curl -X POST "http://localhost:8081/api/v1/fetch?company_id=0190411826001"

# Respuesta:
# {"job_id":"a3f2c8e1","status":"pending","message":"Download started..."}

# Consultar estado:
curl "http://localhost:8081/api/v1/fetch/a3f2c8e1"
```

### 5.2. Vía CLI (alternativa)

```bash
cd /opt/key49-fetch
.venv/bin/python -m src.orchestrator \
    --companies 0190411826001 \
    --year 2026 --month 7

# Backfill (varios meses):
.venv/bin/python -m src.orchestrator \
    --companies 0190411826001 \
    --backfill 2026-01
```

---

## 6. Verificar resultados

```bash
# ─── 6.1. Archivos descargados ─────────────────────────────────
find /data/key49-fetch/xml_downloads -type f | head -20
# xml_downloads/0190411826001/07/01/0401202601...123.xml
# xml_downloads/0190411826001/07/01/0401202601...123.pdf

# ─── 6.2. Estadísticas ─────────────────────────────────────────
cat /opt/key49-fetch/config/stats.json | python3 -m json.tool

# ─── 6.3. Logs por empresa ─────────────────────────────────────
tail -50 /opt/key49-fetch/logs/0190411826001.log
```

---

## 7. Activar servicios (systemd)

```bash
# ─── 7.1. Instalar units ──────────────────────────────────────
cd /opt/key49-fetch
cp deploy/key49-fetch.service /etc/systemd/system/
cp deploy/key49-fetch.timer /etc/systemd/system/
cp deploy/key49-fetch-api.service /etc/systemd/system/
systemctl daemon-reload

# ─── 7.2. Activar API Gateway ─────────────────────────────────
systemctl enable --now key49-fetch-api.service
# API disponible en http://IP:8081/

# ─── 7.3. Activar timer de descargas ──────────────────────────
systemctl enable --now key49-fetch.timer
# Descargas automáticas cada 6 horas

# ─── 7.4. Verificar ───────────────────────────────────────────
systemctl status key49-fetch-api.service
systemctl status key49-fetch.timer
systemctl list-timers key49-fetch.timer
```

---

## 8. Probar API

```bash
# Health
curl http://localhost:8081/api/v1/health

# Listar empresas
curl http://localhost:8081/api/v1/companies

# Listar documentos
curl "http://localhost:8081/api/v1/documents?company_id=0190411826001&year=2026&month=7"

# Descargar un XML
curl "http://localhost:8081/api/v1/documents/{clave_acceso}?company_id=0190411826001&year=2026&month=7&type=1&format=xml" -o factura.xml

# Dashboard web: abrir http://IP:8081/ en navegador
```

---

## 9. Escalar horizontalmente

Si tienes muchos RUCs, despliega instancias adicionales:

```bash
# Instancia 2 (otro servidor)
# Mismos pasos 2-3, pero en .env agregar:
echo "COMPANY_FILTER=0992156406001,1790012345001" >> .env
```

Cada instancia opera independiente. Sin coordinación entre ellas.

---

## 10. Troubleshooting

| Problema | Causa | Solución |
|----------|-------|----------|
| `Connection refused` al SRI | IP baneada o sin acceso | Verificar conectividad a srienlinea.sri.gob.ec |
| reCAPTCHA rechazado | IP con mala reputación | Esperar 1-2h entre ejecuciones |
| `No such file: companies.json` | Ruta incorrecta | Ejecutar desde `/opt/key49-fetch` |
| `FERNET_KEY not set` | Falta .env | Ver sección 4 |
| Tabla vacía (sin error) | No hay comprobantes ese mes | Normal |
| `Playwright: browser not found` | Firefox no instalado | `.venv/bin/playwright install firefox` |
| API no arranca | Puerto ocupado | Cambiar `KEY49_API_PORT` en .env |
| Dashboard en blanco | API no corriendo | `systemctl status key49-fetch-api` |

---

## 11. Monitoreo diario

```bash
# Health check
cd /opt/key49-fetch && .venv/bin/python -m src.orchestrator --health

# Dashboard web
# Abrir http://IP:8081/

# Últimos logs
journalctl -u key49-fetch.service --since "6 hours ago"

# Auditoría de webhooks
cat /opt/key49-fetch/logs/webhooks/*.jsonl | python3 -m json.tool
```
