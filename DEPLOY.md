# Key49-Fetch — Guía de Despliegue y Primeros RUCs

> Última actualización: 2026-07-17 | Versión: v0.6.0

---

## 1. Requisitos del servidor

| Componente | Mínimo |
|-----------|--------|
| OS | Linux (Ubuntu 22.04+ recomendado) |
| RAM | 2 GB (Firefox headless ~500 MB por ejecución) |
| Disco | 5 GB (depende del volumen de comprobantes) |
| Python | 3.10+ |
| Red | Acceso a `srienlinea.sri.gob.ec` |

---

## 2. Instalación

```bash
# ─── 2.1. Clonar el proyecto ───────────────────────────────────
cd /opt
git clone https://github.com/auracore/key49-fetch.git
cd key49-fetch

# ─── 2.2. Crear usuario de servicio ────────────────────────────
sudo useradd -r -s /bin/false key49
sudo mkdir -p /data/key49-fetch/xml_downloads
sudo chown -R key49:key49 /opt/key49-fetch /data/key49-fetch

# ─── 2.3. Entorno virtual Python ──────────────────────────────
sudo -u key49 python3 -m venv .venv
sudo -u key49 .venv/bin/pip install -r requirements.txt

# ─── 2.4. Instalar navegador Firefox para Playwright ──────────
sudo -u key49 .venv/bin/playwright install firefox

# Si falla por falta de dependencias del sistema:
# sudo -u key49 .venv/bin/playwright install-deps firefox
```

---

## 3. Configuración

```bash
# ─── 3.1. Copiar plantilla de variables ───────────────────────
sudo -u key49 cp .env.example .env
sudo -u key49 nano .env
```

### Variables mínimas obligatorias

```bash
# Generar una clave Fernet para encriptar contraseñas SRI
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Copiar el resultado ↓
```

```bash
# .env — valores mínimos
FERNET_KEY=la-clave-generada-arriba

# API (opcional — sin esto no hay auth, modo dev)
# API_KEYS=clave-api-1,clave-api-2

# Alertas (opcional)
# ALERT_WEBHOOK_URL=https://hooks.slack.com/services/...
# ALERT_THRESHOLD=3
```

---

## 4. Registrar los primeros RUCs

Editar `config/companies.json`:

```json
[
    {
        "company_id": "0195160252001",
        "ruc": "0195160252001",
        "business_name": "AuraCore Systems",
        "sri_password_encrypted": "LA_CLAVE_DEL_SRI",
        "is_active": true,
        "download_types": [1, 6],
        "schedule": "daily",
        "proxy_profile": null,
        "webhook_url": null,
        "webhook_secret": null
    },
    {
        "company_id": "0992156406001",
        "ruc": "0992156406001",
        "business_name": "Segunda Empresa SA",
        "sri_password_encrypted": "OTRA_CLAVE_SRI",
        "is_active": true,
        "download_types": [1, 2, 3, 4, 6],
        "schedule": "weekly",
        "proxy_profile": null,
        "webhook_url": "https://erp.empresa.com/api/webhooks/key49",
        "webhook_secret": "secreto-compartido-con-el-erp"
    }
]
```

> **Nota**: `sri_password_encrypted` se guarda en texto plano la primera vez.
> Al ejecutar el orquestador, se encripta automáticamente con Fernet.
> También puedes usar la variable de entorno `SRI_PASSWORD_0195160252001` para
> pasar la clave sin escribirla en el JSON.

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

> ⚠️ **Importante**: Registrar un RUC en `companies.json` NO dispara descargas automáticas.
> La primera descarga debe solicitarse manualmente vía API o CLI.
> Luego el timer (systemd) continúa descargando periódicamente.

```bash
# ─── 5.1. Vía API (recomendado) ─────────────────────────────────
# Asegúrate que la API esté corriendo:
sudo -u key49 .venv/bin/python -m src.api.app &

# Disparar descarga para el mes corriente:
curl -X POST \
  "http://localhost:8081/api/v1/fetch?company_id=0195160252001"

# Con mes específico:
curl -X POST \
  "http://localhost:8081/api/v1/fetch?company_id=0195160252001&year=2026&month=4"

# ─── 5.2. Vía CLI (alternativa) ─────────────────────────────────
# Si tienes display (entorno gráfico):
sudo -u key49 .venv/bin/python -m src.orchestrator \
    --companies 0195160252001 \
    --year 2026 --month 7 \
    --visible

# ─── 5.2. Modo headless (servidor sin GUI) ────────────────────
sudo -u key49 .venv/bin/python -m src.orchestrator \
    --companies 0195160252001 \
    --year 2026 --month 7

# ─── 5.3. Backfill (varios meses de una vez) ──────────────────
sudo -u key49 .venv/bin/python -m src.orchestrator \
    --companies 0195160252001 \
    --backfill 2026-01
```

### Qué esperar

```
══════════════════════════════════════════════
🚀 Key49-Fetch Multi-Company Orchestrator
   Period: 2026-07
   Companies: 1 active
   Rate limit: 180s between companies
══════════════════════════════════════════════

──────────────────────────────────────────────
📋 Company 1/1: AuraCore Systems (0195160252001)
   Types: [1, 6]
──────────────────────────────────────────────
🔐 Abriendo página del SRI para login...
   ✅ RUC rellenado: 0195160252001
   ✅ Clave rellenada
   ✅ Clic en 'Ingresar' realizado

══════════════════════════════════════════════
📋 Tipo 1/2: Factura (código 01)
📁 Destino: xml_downloads/0195160252001/07/01
══════════════════════════════════════════════
✅ Tabla detectada con 8 filas
📥 Procesando 8 comprobantes (XML + PDF)...
🎉 Descarga completada: 8 nuevos, 0 existentes, 0 errores

══════════════════════════════════════════════
📋 Tipo 2/2: Comprobante de Retención (código 06)
📁 Destino: xml_downloads/0195160252001/07/06
══════════════════════════════════════════════
⏭️  No existen comprobantes para este tipo.

══════════════════════════════════════════════
🎉 ALL COMPANIES COMPLETE
   Downloaded: 8 | Skipped: 0 | Errors: 0
   Companies processed: 1
══════════════════════════════════════════════
```

---

## 6. Verificar resultados

```bash
# ─── 6.1. Archivos descargados ─────────────────────────────────
find /data/key49-fetch/xml_downloads -type f | head -20

# Estructura esperada:
# xml_downloads/0195160252001/07/01/0401202601...123.xml
# xml_downloads/0195160252001/07/01/0401202601...123.pdf

# ─── 6.2. Estadísticas ─────────────────────────────────────────
cat config/stats.json | python3 -m json.tool

# ─── 6.3. Logs por empresa ─────────────────────────────────────
tail -50 logs/0195160252001.log
```

---

## 7. Activar el API Gateway

```bash
# ─── 7.1. Arrancar manualmente ─────────────────────────────────
sudo -u key49 .venv/bin/python -m src.api.app

# ─── 7.2. Probar endpoints ─────────────────────────────────────
curl http://localhost:8081/api/v1/health
curl http://localhost:8081/api/v1/companies
curl "http://localhost:8081/api/v1/documents?company_id=0195160252001&year=2026&month=7"
curl "http://localhost:8081/api/v1/documents/{clave_acceso}?company_id=0195160252001&year=2026&month=7&type=1&format=xml" -o factura.xml

# ─── 7.3. Disparar descarga bajo demanda ────────────────────────
# Registrar un RUC NO dispara descarga automática.
# Usa este endpoint para la descarga inicial:
curl -X POST -H "X-API-Key: my-key" \
  "http://localhost:8081/api/v1/fetch?company_id=0195160252001"

# Consultar estado del job:
curl -H "X-API-Key: my-key" \
  "http://localhost:8081/api/v1/fetch/{job_id}"

# Listar últimos jobs:
curl -H "X-API-Key: my-key" \
  "http://localhost:8081/api/v1/fetch"

# ─── 7.4. Dashboard web ────────────────────────────────────────
# Abrir en navegador: http://IP-DEL-SERVIDOR:8081/
```

---

## 8. Instalar como servicio (systemd)

```bash
# ─── 8.1. Copiar units ────────────────────────────────────────
sudo cp deploy/key49-fetch.service /etc/systemd/system/
sudo cp deploy/key49-fetch.timer /etc/systemd/system/
sudo cp deploy/key49-fetch-api.service /etc/systemd/system/

# ─── 8.2. Ajustar rutas en los units si es necesario ───────────
# Por defecto asumen:
#   WorkingDirectory=/opt/key49-fetch
#   ExecStart=/opt/key49-fetch/.venv/bin/python ...
# Si instalaste en otra ruta, editar los archivos .service

# ─── 8.3. Activar ──────────────────────────────────────────────
sudo systemctl daemon-reload

# Timer de descargas (cada 6 horas)
sudo systemctl enable --now key49-fetch.timer

# API Gateway (siempre corriendo)
sudo systemctl enable --now key49-fetch-api.service

# ─── 8.4. Verificar ────────────────────────────────────────────
systemctl status key49-fetch.timer
systemctl status key49-fetch-api.service
systemctl list-timers key49-fetch.timer

# ─── 8.5. Ver logs ─────────────────────────────────────────────
journalctl -u key49-fetch.service -f
journalctl -u key49-fetch-api.service -f
```

---

## 9. Escalar horizontalmente (múltiples instancias)

Si tienes muchos RUCs, despliega instancias adicionales, cada una con su subset:

```bash
# ─── Instancia 2 en otro servidor ──────────────────────────────
# Mismos pasos 2-4, pero en .env:
echo "COMPANY_FILTER=0992156406001,1790012345001" >> .env

# O por línea de comandos:
python -m src.orchestrator --companies 0992156406001,1790012345001
```

Cada instancia opera independiente. Sin coordinación entre ellas porque:
- Rate limiting es por instancia
- Skip-existing evita duplicados
- Los subsets de RUCs no se solapan

---

## 10. Troubleshooting

| Problema | Causa probable | Solución |
|----------|---------------|----------|
| `Connection refused` al SRI | IP baneada o sin acceso | Probar con `--visible` para ver el navegador; verificar conectividad |
| reCAPTCHA rechazado siempre | IP con mala reputación | Esperar 1-2h entre ejecuciones; considerar proxy rotativo |
| `No such file: config/companies.json` | Ruta incorrecta | Ejecutar desde `/opt/key49-fetch` o usar `--config` |
| `FERNET_KEY not set` | Falta variable de entorno | Generar clave y agregar a `.env` (ver paso 3) |
| Tabla vacía (sin errores) | No hay comprobantes para ese tipo/mes | Normal — el SRI responde "No existen datos" |
| `Playwright: browser not found` | Firefox no instalado | `playwright install firefox` |
| API no arranca | Puerto ocupado | `KEY49_API_PORT=8081` (cambiar en `.env`) |
| Dashboard en blanco | API no corriendo o CORS | Verificar `systemctl status key49-fetch-api` |

---

## 11. Monitoreo diario

```bash
# Health check rápido
python -m src.orchestrator --health

# Dashboard web
open http://IP-SERVIDOR:8081/

# Últimos logs de cada empresa
tail -5 logs/*.log

# Auditoría de webhooks
cat logs/webhooks/*.jsonl | python3 -m json.tool
```
