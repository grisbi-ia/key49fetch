# Key49-Fetch — Diseño de Integración con Key49

> **Propósito**: Este documento define la arquitectura, contratos y cambios necesarios para integrar Key49-Fetch (descarga de comprobantes electrónicos del SRI) con Key49 (plataforma SaaS de facturación electrónica).
>
> **Audiencia**: Copilot / desarrollador que trabaje sobre el proyecto Key49 (Quarkus).

---

## 1. Contexto

### Key49 (existente)

- **Stack**: Quarkus + Postgres + MinIO + Redis + RabbitMQ (SmallRye Reactive Messaging)
- **Función**: SaaS multiempresa para emisión de documentos electrónicos al SRI Ecuador
- **Multi-tenancy**: Un esquema Postgres por tenant (patrón de nombre)
- **MinIO**: Bucket global con prefijos por tenant
- **Scheduler**: `@Scheduled` de Quarkus
- **Deploy**: Docker Compose

### Key49-Fetch (nuevo, este proyecto)

- **Stack**: Python 3 + Playwright (Firefox) + httpx
- **Función**: Worker autónomo que descarga comprobantes electrónicos recibidos desde el SRI
- **Características probadas**:
  - Login automático al SRI
  - Bypass de reCAPTCHA Enterprise por confianza nativa (sin CapSolver)
  - Descarga paralela de XMLs y PDFs vía HTTP directo
  - Skip de archivos ya descargados
  - Reintentos automáticos con backoff
  - Modo headless (sin GUI)
- **Archivo core**: `sri_downloader.py` (funcional, probado)

---

## 2. Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│                      Key49 (Quarkus)                        │
│                                                             │
│  @Scheduled (cada 30 min)                                   │
│    → Para cada tenant activo con sri_password:              │
│      → Consulta claves_acceso ya registradas del periodo    │
│      → Publica job en RabbitMQ                              │
│                                                             │
│  Consumer fetch.results:                                    │
│    → Recibe resultado de Fetch                              │
│    → INSERT en comprobante_recibido (esquema del tenant)    │
│    → POST webhook al tenant                                 │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Postgres │  │  MinIO   │  │  Redis   │  │ RabbitMQ │   │
│  │(esquemas)│  │(archivos)│  │ (cache)  │  │ (colas)  │   │
│  └────▲─────┘  └────▲─────┘  └──────────┘  └────┬─────┘   │
└───────┼──────────────┼───────────────────────────┼──────────┘
        │              │                           │
        │              │         ┌─────────────────┘
        │              │         │
        │              │         ▼
┌───────────────────────────────────────────────────────────────┐
│                   Key49-Fetch (Python)                        │
│                                                              │
│  1. Consume cola: key49.fetch.jobs                           │
│  2. Login SRI → descarga XMLs/PDFs (solo nuevos)            │
│  3. Sube archivos a MinIO                                    │
│  4. Publica resultado en: key49.fetch.results                │
│  5. Elimina archivos temporales locales                      │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Contratos RabbitMQ

### Exchange

```
Nombre:       key49.fetch
Tipo:         topic
Durable:      true
```

### Queue: Jobs (Key49 → Fetch)

```
Queue:        key49.fetch.jobs
Routing key:  fetch.job
```

**Mensaje**:

```json
{
  "job_id": "uuid-v4",
  "tenant_id": "acme-corp",
  "schema": "tenant_acme",
  "ruc": "0190411826001",
  "password": "clave-sri-desencriptada",
  "year": 2026,
  "month": 4,
  "types": [1, 2, 3, 4, 6],
  "known_claves": [
    "0401202601019043547400120010040008603911234567817",
    "0401202601179001093700120011710208325052083250511"
  ],
  "minio_prefix": "acme-corp/recibidos/2026-04"
}
```

| Campo          | Tipo     | Descripción                                                             |
| -------------- | -------- | ----------------------------------------------------------------------- |
| `job_id`       | UUID     | Identificador único del job para trazabilidad                           |
| `tenant_id`    | string   | ID del tenant en Key49                                                  |
| `schema`       | string   | Nombre del esquema Postgres del tenant                                  |
| `ruc`          | string   | RUC del tenant (13 dígitos)                                             |
| `password`     | string   | Clave SRI desencriptada en memoria. **Fetch no la persiste**            |
| `year`         | int      | Año de consulta                                                         |
| `month`        | int      | Mes de consulta (1-12)                                                  |
| `types`        | int[]    | Tipos de comprobante: 1=Factura, 2=Liquidación, 3=NC, 4=ND, 6=Retención |
| `known_claves` | string[] | Claves de acceso (49 dígitos) ya registradas en BD. Fetch las salta     |
| `minio_prefix` | string   | Prefijo en MinIO donde subir los archivos                               |

### Queue: Resultados (Fetch → Key49)

```
Queue:        key49.fetch.results
Routing key:  fetch.result
```

**Mensaje**:

```json
{
  "job_id": "uuid-v4",
  "tenant_id": "acme-corp",
  "schema": "tenant_acme",
  "status": "completed",
  "documents": [
    {
      "clave_acceso": "0501202601019043547400120010020009758681234567810",
      "tipo": 1,
      "emisor_ruc": "0190435474001",
      "emisor_nombre": "ESTACION DE SERVICIOS NEOGAS S.A.",
      "xml_key": "acme-corp/recibidos/2026-04/0501202601019043...810.xml",
      "pdf_key": "acme-corp/recibidos/2026-04/0501202601019043...810.pdf"
    }
  ],
  "summary": {
    "total_in_sri": 53,
    "already_known": 50,
    "new_downloaded": 3,
    "errors": 0
  },
  "error_message": null
}
```

| Campo                    | Tipo   | Descripción                                                      |
| ------------------------ | ------ | ---------------------------------------------------------------- |
| `status`                 | string | `completed`, `partial` (algunos errores), `failed` (error total) |
| `documents`              | array  | Solo documentos **nuevos** descargados en esta ejecución         |
| `documents[].xml_key`    | string | Ruta del objeto XML en MinIO. `null` si no se pudo descargar     |
| `documents[].pdf_key`    | string | Ruta del objeto PDF en MinIO. `null` si no existe o falló        |
| `summary.total_in_sri`   | int    | Total de comprobantes que aparecen en la tabla del SRI           |
| `summary.already_known`  | int    | Cantidad que ya estaban en `known_claves` (saltados)             |
| `summary.new_downloaded` | int    | Cantidad de nuevos descargados exitosamente                      |
| `summary.errors`         | int    | Cantidad de descargas fallidas tras agotar reintentos            |
| `error_message`          | string | Mensaje si `status=failed` (ej: login falló, captcha agotado)    |

---

## 4. Cambios requeridos en Key49 (Quarkus)

### 4.1. Nuevo campo en entidad Tenant

Agregar `sriPassword` a la entidad del tenant. Debe almacenarse **encriptada** (AES-256-GCM o similar). Solo se desencripta al construir el mensaje del job.

```sql
ALTER TABLE public.tenant ADD COLUMN sri_password_encrypted VARCHAR(512);
```

### 4.2. Nueva tabla por esquema: `comprobante_recibido`

Agregar al migration script que crea esquemas de tenant:

```sql
CREATE TABLE {schema}.comprobante_recibido (
    id              BIGSERIAL PRIMARY KEY,
    clave_acceso    VARCHAR(49) NOT NULL UNIQUE,
    tipo            SMALLINT NOT NULL,
    fecha_emision   DATE,
    emisor_ruc      VARCHAR(13),
    emisor_nombre   VARCHAR(300),
    minio_xml_key   VARCHAR(500),
    minio_pdf_key   VARCHAR(500),
    downloaded_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    webhook_sent    BOOLEAN DEFAULT FALSE,
    webhook_sent_at TIMESTAMP
);

CREATE INDEX idx_comp_recibido_clave ON {schema}.comprobante_recibido (clave_acceso);
CREATE INDEX idx_comp_recibido_periodo ON {schema}.comprobante_recibido (fecha_emision);
CREATE INDEX idx_comp_recibido_tipo ON {schema}.comprobante_recibido (tipo);
```

### 4.3. Entidad JPA: ComprobanteRecibido

```java
@Entity
@Table(name = "comprobante_recibido")
public class ComprobanteRecibido extends PanacheEntity {
    @Column(name = "clave_acceso", nullable = false, unique = true, length = 49)
    public String claveAcceso;

    @Column(nullable = false)
    public Short tipo;

    @Column(name = "fecha_emision")
    public LocalDate fechaEmision;

    @Column(name = "emisor_ruc", length = 13)
    public String emisorRuc;

    @Column(name = "emisor_nombre", length = 300)
    public String emisorNombre;

    @Column(name = "minio_xml_key", length = 500)
    public String minioXmlKey;

    @Column(name = "minio_pdf_key", length = 500)
    public String minioPdfKey;

    @Column(name = "downloaded_at", nullable = false)
    public Instant downloadedAt;

    @Column(name = "webhook_sent")
    public boolean webhookSent;

    @Column(name = "webhook_sent_at")
    public Instant webhookSentAt;
}
```

### 4.4. Scheduler: Dispatch de jobs

```java
@ApplicationScoped
public class FetchJobScheduler {

    @Inject
    TenantRepository tenantRepo;

    @Inject
    @Channel("fetch-jobs-out")
    Emitter<FetchJob> fetchJobEmitter;

    @Scheduled(every = "30m")
    void dispatchFetchJobs() {
        LocalDate today = LocalDate.now();
        int year = today.getYear();
        int month = today.getMonthValue();

        List<Tenant> tenants = tenantRepo.findWithSriCredentials();
        for (Tenant t : tenants) {
            // Consultar claves ya descargadas para este periodo
            List<String> knownClaves = ComprobanteRecibido
                .find("fecha_emision >= ?1 AND fecha_emision < ?2",
                      today.withDayOfMonth(1),
                      today.withDayOfMonth(1).plusMonths(1))
                .project(String.class)  // TODO: ajustar al mecanismo de esquema
                .list();

            FetchJob job = new FetchJob();
            job.jobId = UUID.randomUUID().toString();
            job.tenantId = t.id;
            job.schema = t.schemaName;
            job.ruc = t.ruc;
            job.password = decrypt(t.sriPasswordEncrypted); // Desencripta en memoria
            job.year = year;
            job.month = month;
            job.types = List.of(1, 2, 3, 4, 6); // Todos los tipos
            job.knownClaves = knownClaves;
            job.minioPrefix = t.id + "/recibidos/" + year + "-" + String.format("%02d", month);

            fetchJobEmitter.send(job);
        }
    }
}
```

### 4.5. Consumer: Procesar resultados

```java
@ApplicationScoped
public class FetchResultConsumer {

    @Inject
    WebhookService webhookService;

    @Incoming("fetch-results-in")
    void onFetchResult(FetchResult result) {
        if (result.documents == null || result.documents.isEmpty()) return;

        // Cambiar al esquema del tenant
        setSchema(result.schema);

        for (FetchDocument doc : result.documents) {
            ComprobanteRecibido comp = new ComprobanteRecibido();
            comp.claveAcceso = doc.claveAcceso;
            comp.tipo = doc.tipo;
            comp.emisorRuc = doc.emisorRuc;
            comp.emisorNombre = doc.emisorNombre;
            comp.minioXmlKey = doc.xmlKey;
            comp.minioPdfKey = doc.pdfKey;
            comp.downloadedAt = Instant.now();
            comp.fechaEmision = extractFechaFromClave(doc.claveAcceso);
            comp.persist();
        }

        // Notificar al tenant via webhook
        webhookService.notify(result.tenantId, "new_documents", result);
    }

    /** Extrae fecha de emisión de la clave de acceso (posiciones 0-7: ddmmaaaa) */
    private LocalDate extractFechaFromClave(String clave) {
        int day = Integer.parseInt(clave.substring(0, 2));
        int month = Integer.parseInt(clave.substring(2, 4));
        int year = Integer.parseInt(clave.substring(4, 8));
        return LocalDate.of(year, month, day);
    }
}
```

### 4.6. Configuración RabbitMQ (application.properties)

```properties
# Exchange
mp.messaging.outgoing.fetch-jobs-out.connector=smallrye-rabbitmq
mp.messaging.outgoing.fetch-jobs-out.exchange.name=key49.fetch
mp.messaging.outgoing.fetch-jobs-out.exchange.type=topic
mp.messaging.outgoing.fetch-jobs-out.routing-key=fetch.job
mp.messaging.outgoing.fetch-jobs-out.exchange.durable=true

mp.messaging.incoming.fetch-results-in.connector=smallrye-rabbitmq
mp.messaging.incoming.fetch-results-in.exchange.name=key49.fetch
mp.messaging.incoming.fetch-results-in.queue.name=key49.fetch.results
mp.messaging.incoming.fetch-results-in.routing-keys=fetch.result
mp.messaging.incoming.fetch-results-in.exchange.durable=true
```

---

## 5. Estructura de Key49-Fetch

```
key49-fetch/
├── sri_downloader.py       # Core de descarga (ya funcional, no modificar lógica)
├── worker.py               # Consumidor RabbitMQ → orquesta → publica resultado
├── minio_upload.py          # Upload a MinIO + cleanup local
├── config.py               # Variables de entorno
├── requirements.txt        # Dependencias Python
├── Dockerfile              # Imagen con Python + Playwright + Firefox
├── .env.example            # Plantilla de variables
└── KEY49_FETCH_INTEGRATION.md  # Este documento
```

### Archivos nuevos por crear en Key49-Fetch

**`worker.py`**: Consume mensajes de `key49.fetch.jobs`, ejecuta `sri_downloader.download_xmls()` con los parámetros del mensaje, sube archivos a MinIO, publica resultado en `key49.fetch.results`.

**`minio_upload.py`**: Usa `minio` (Python SDK) para subir archivos con el prefijo del tenant. Borra archivos locales después del upload.

**`config.py`**: Lee variables de entorno: `RABBITMQ_URL`, `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`, `REDIS_URL`.

**`Dockerfile`**:

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install firefox
COPY . .
CMD ["python", "worker.py"]
```

---

## 6. Estado actual y refactoring pendiente en sri_downloader.py

### Ya implementado

- **Loop de múltiples tipos de comprobante** en una sola sesión de browser: login una vez, itera los tipos solicitados (`--types 1,2,3,4,6`). Cada tipo se procesa secuencialmente reutilizando la misma sesión autenticada.
- **Selección fuzzy de tipo**: Los códigos de tipo no coinciden 1:1 con los `<option value>` del `<select>` del SRI. Se usa `page.evaluate()` con búsqueda por texto (`.toUpperCase().includes()`) para resolver el valor real.
- **Estructura de archivos por RUC y tipo de documento**:
  ```
  xml_downloads/
  └── {ruc}/
      ├── 01/          # Factura (tipo 1)
      │   ├── {clave_acceso}.xml
      │   └── {clave_acceso}.pdf
      ├── 02/          # Liquidación de compra (tipo 2)
      ├── 03/          # Nota de Crédito (tipo 3)
      ├── 04/          # Nota de Débito (tipo 4)
      └── 06/          # Comprobante de Retención (tipo 6)
  ```
- **Reintentos unificados**: Tanto el rechazo de reCAPTCHA como el timeout del SRI (tabla que nunca carga) disparan el mismo flujo de reload + retry (hasta 5 reintentos con backoff progresivo 8-20s).
- **Detección de "sin datos"**: Si el SRI responde "No existen comprobantes" o "No existen datos", se salta el tipo inmediatamente sin agotar reintentos.
- **Skip de archivos existentes**: No re-descarga XMLs/PDFs que ya existen en disco.
- **Resumen por tipo y total**: Al finalizar cada tipo imprime un resumen parcial; al finalizar todos imprime un `RESUMEN TOTAL` acumulado.

### Tipos de comprobante confirmados en el SRI (comprobantes recibidos)

| Valor `<option>` | Tipo de comprobante                                       |
| ---------------- | --------------------------------------------------------- |
| 1                | Factura                                                   |
| 2                | Liquidación de compra de bienes y prestación de servicios |
| 3                | Notas de Crédito                                          |
| 4                | Notas de Débito                                           |
| 6                | Comprobante de Retención                                  |

> **Nota**: No existen los valores 5, 7, ni "Guía de Remisión" en el `<select>` de comprobantes recibidos del SRI.

### Refactoring pendiente para integración con worker.py

1. **`download_xmls()` debe retornar** una lista de documentos descargados (no solo imprimir)
2. **Aceptar `known_claves`** como parámetro para skip por clave de acceso (no solo por archivo en disco)
3. **Aceptar `output_dir` temporal** (`/tmp/fetch-{job_id}/`)

Estos cambios son internos a Key49-Fetch y no afectan el contrato con Key49.

---

## 7. Protección contra ejecuciones concurrentes

### Problema

El `@Scheduled(every = "30m")` de Quarkus podría despachar un segundo job para el mismo RUC mientras el primero aún está en ejecución. Dos sesiones de Playwright con el mismo RUC simultáneamente en el SRI pueden causar:

- Sesiones mutuamente invalidadas (el SRI detecta doble login)
- Descargas duplicadas
- Consumo innecesario de recursos (cada sesión ~300-500 MB de RAM)

### Análisis de tiempos

| Escenario                                    | Duración estimada |
| -------------------------------------------- | ----------------- |
| Caso típico (pocos captchas rechazados)      | ~5 min            |
| Caso con captchas rechazados en varios tipos | ~10-14 min        |
| Peor caso (agota reintentos en un tipo)      | ~14 min           |

Con `@Scheduled(every = "30m")`, el riesgo de solapamiento es bajo pero real, especialmente si reCAPTCHA Enterprise rechaza múltiples intentos.

### Solución: Redis Lock por RUC

Implementar un lock distribuido por RUC en `worker.py` usando Redis:

```python
import redis

LOCK_TTL = 900  # 15 minutos (mayor que el peor caso)

def acquire_lock(redis_client: redis.Redis, ruc: str) -> bool:
    """Intenta adquirir lock exclusivo para este RUC."""
    key = f"key49:fetch:lock:{ruc}"
    return redis_client.set(key, "1", nx=True, ex=LOCK_TTL)

def release_lock(redis_client: redis.Redis, ruc: str):
    """Libera el lock del RUC."""
    key = f"key49:fetch:lock:{ruc}"
    redis_client.delete(key)
```

**Flujo en `worker.py`**:

1. Recibe mensaje del job
2. Intenta `acquire_lock(ruc)` → si falla, **nack** el mensaje (vuelve a la cola)
3. Ejecuta `download_xmls()` + upload a MinIO
4. Publica resultado en `key49.fetch.results`
5. `release_lock(ruc)` en bloque `finally`

**Alternativa en Key49 (Quarkus)**: El scheduler podría consultar Redis antes de publicar el job, evitando enviar mensajes innecesarios. Ambas protecciones pueden coexistir (defensa en profundidad).

### Configuración adicional

```yaml
key49-fetch:
  environment:
    - REDIS_URL=redis://redis:6379/0
  depends_on:
    - redis
```

---

## 8. Docker Compose (agregar a Key49)

```yaml
key49-fetch:
  build: ./key49-fetch
  environment:
    - RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672
    - MINIO_ENDPOINT=minio:9000
    - MINIO_ACCESS_KEY=${MINIO_ACCESS_KEY}
    - MINIO_SECRET_KEY=${MINIO_SECRET_KEY}
    - MINIO_BUCKET=key49
    - MINIO_SECURE=false
  depends_on:
    - rabbitmq
    - minio
  restart: unless-stopped
  deploy:
    resources:
      limits:
        memory: 1G
```

---

## 9. Seguridad

| Aspecto                        | Implementación                                                                  |
| ------------------------------ | ------------------------------------------------------------------------------- |
| Credenciales SRI en BD         | Encriptadas con AES-256-GCM. Clave simétrica en env var del server              |
| Credenciales en mensajes       | Desencriptadas en memoria por Key49, enviadas por RabbitMQ (red interna Docker) |
| Fetch no persiste credenciales | Las recibe en el mensaje, las usa en memoria, no las escribe a disco ni log     |
| MinIO                          | Credenciales por env vars, red interna Docker                                   |
| RabbitMQ                       | Red interna Docker, no expuesto a internet                                      |
| Logs                           | No imprimir passwords. Ofuscar RUC en logs si es necesario                      |

---

## 10. Webhook al tenant

Cuando Key49 recibe el resultado de Fetch y registra documentos nuevos, envía un webhook:

```
POST {tenant.webhookUrl}
Content-Type: application/json
X-Key49-Signature: HMAC-SHA256(body, tenant.webhookSecret)

{
  "event": "documents.received",
  "tenant_id": "acme-corp",
  "period": "2026-04",
  "new_count": 3,
  "documents": [
    {
      "clave_acceso": "0501202601019043...",
      "tipo": "FACTURA",
      "emisor_ruc": "0190435474001",
      "emisor_nombre": "NEOGAS S.A.",
      "fecha_emision": "2026-04-05"
    }
  ]
}
```

---

## 11. Orden de implementación sugerido

### En Key49-Fetch (Python):

1. ✅ Core de descarga funcional (`sri_downloader.py`)
2. ✅ Skip de archivos existentes
3. ✅ Headless por defecto
4. ⬜ Refactorear `download_xmls()` para retornar lista de documentos
5. ✅ Loop de múltiples tipos de comprobante con estructura `{ruc}/{tipo_code}/`
6. ⬜ `minio_upload.py`
7. ⬜ `worker.py` (consumidor RabbitMQ)
8. ⬜ `Dockerfile`

### En Key49 (Quarkus):

1. ⬜ Campo `sri_password_encrypted` en entity Tenant
2. ⬜ Tabla `comprobante_recibido` en migration de esquemas
3. ⬜ Entity `ComprobanteRecibido`
4. ⬜ Configuración RabbitMQ (exchange + queues)
5. ⬜ `FetchJobScheduler` (@Scheduled)
6. ⬜ `FetchResultConsumer` (SmallRye @Incoming)
7. ⬜ API REST para consultar comprobantes recibidos (frontend)
8. ⬜ Webhook dispatch
9. ⬜ Docker Compose: agregar servicio key49-fetch
