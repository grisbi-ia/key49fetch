# Key49-Fetch — Project Overview

## What is Key49-Fetch?

Key49-Fetch is an **automated electronic document downloader** for Ecuador's tax authority (SRI — Servicio de Rentas Internas). It logs into the SRI portal, solves reCAPTCHA challenges, navigates the UI, and downloads XML and PDF files for received electronic invoices (comprobantes electrónicos recibidos).

It is designed as the **fetch worker** for the **Key49 SaaS platform** (Quarkus-based electronic invoicing system), but can operate standalone.

## How It Works

```
User/ERP ──request──> API Gateway ──job──> RabbitMQ ──consume──> sri_downloader.py (Python)
                                                                      │
                                                                      ├── 1. Login SRI (Playwright + Firefox)
                                                                      ├── 2. Browse menus (human-like)
                                                                      ├── 3. Solve reCAPTCHA (native trust scoring)
                                                                      ├── 4. Query comprobantes by type/month
                                                                      ├── 5. Download XMLs + PDFs via HTTP
                                                                      ├── 6. Upload to MinIO
                                                                      └── 7. Publish result to RabbitMQ
```

### Core Components

| Component | Tech | Purpose |
|-----------|------|---------|
| `sri_downloader.py` | Python 3 + Playwright | Main downloader script (headless Firefox) |
| `bot_descargas_v2/` | Node.js + Express | Reference implementation (AstroBot) |
| RabbitMQ | Messaging | Job queue (fetch.jobs / fetch.results) |
| MinIO | Object storage | Document persistence |

### Supported Document Types

| Code | Name (ES) | Name (EN) |
|------|-----------|------------|
| 1 | Factura | Invoice |
| 2 | Liquidación de compra | Purchase Settlement |
| 3 | Notas de Crédito | Credit Notes |
| 4 | Notas de Débito | Debit Notes |
| 6 | Comprobante de Retención | Withholding Certificate |

### Output Structure

```
{bucket}/{ruc}/{month:02d}/{type:02d}/
├── {access_key}.xml
└── {access_key}.pdf
```

## Development Standards

### Language & Naming

- **All code**: English (variables, functions, comments, commit messages)
- **All database objects**: English

### Database Conventions

- **Tables**: plural, snake_case (`companies`, `documents`, `fetch_jobs`)
- **Columns**: singular, snake_case (`created_at`, `access_key`, `company_id`)
- **Primary key**: `{table_singular}_id` (e.g., table `companies` → PK `company_id`)
- **Foreign keys**: same pattern (e.g., `company_id` references `companies.company_id`)
- **Timestamps**: `created_at`, `updated_at` (UTC)
- **Soft delete**: `deleted_at` (nullable timestamp)

### Examples

```sql
CREATE TABLE companies (
    company_id   BIGSERIAL PRIMARY KEY,
    ruc          VARCHAR(13)  NOT NULL UNIQUE,
    business_name VARCHAR(300) NOT NULL,
    sri_password_encrypted VARCHAR(512),
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at   TIMESTAMPTZ
);

CREATE TABLE documents (
    document_id    BIGSERIAL PRIMARY KEY,
    company_id     BIGINT NOT NULL REFERENCES companies(company_id),
    access_key     VARCHAR(49) NOT NULL,
    document_type  VARCHAR(2) NOT NULL,
    emission_date  DATE NOT NULL,
    emitter_ruc    VARCHAR(13),
    emitter_name   VARCHAR(300),
    total_amount   DECIMAL(14,2),
    xml_path       VARCHAR(500),
    pdf_path       VARCHAR(500),
    status         VARCHAR(20) NOT NULL DEFAULT 'downloaded',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(company_id, access_key)
);
```

### Git Workflow

- **Tag format**: `v{major}.{minor}.{patch}` (e.g., `v1.0.0`, `v1.1.0`, `v2.0.0`)
- **Branch strategy**: `main` (production), feature branches merged via PR
- **Commit messages**: English, imperative mood (`Add retry logic for captcha`, `Fix session timeout`)

### Phase Completion Checklist

Before tagging a phase:
1. [ ] Code implemented and reviewed
2. [ ] Tests pass (unit + integration)
3. [ ] `ROADMAP.md` updated (mark phase as done)
4. [ ] `PROGRESS.md` updated with phase details
5. [ ] `CHANGELOG.md` updated
6. [ ] Git tag created (`v{major}.{minor}.{patch}`)

### Python Code Style

- Follow PEP 8
- Type hints on all function signatures
- Docstrings on public functions (Google style)
- `async/await` for all I/O operations
- Environment variables for configuration (never hardcode secrets)

### Security Rules

- **Never log credentials** (RUC passwords, API keys)
- **SRI passwords**: encrypted at rest (AES-256), decrypted only in memory
- **MinIO access**: signed URLs with expiration for external access
- **Environment files**: `.env` in `.gitignore`, `.env.example` committed
