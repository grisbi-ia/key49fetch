"""Key49-Fetch REST API — FastAPI application.

Serves documents downloaded from SRI via a RESTful API with API key auth.

Endpoints:
    GET /api/v1/health                    Health check
    GET /api/v1/companies                  List companies
    GET /api/v1/documents                  List/download documents
    GET /api/v1/documents/{access_key}     Download single document

Usage:
    python -m src.api.app
    uvicorn src.api.app:app --host 0.0.0.0 --port 8081
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from starlette.status import HTTP_404_NOT_FOUND

from src.api.auth import verify_api_key
from src.api.companies import list_companies
from src.api.documents import scan_documents

# ─── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Key49-Fetch API",
    description="REST API for SRI electronic document access",
    version="0.6.0",
    docs_url="/docs" if os.environ.get("ENABLE_DOCS", "1") == "1" else None,
    redoc_url=None,
)

# Configurable via env vars
OUTPUT_BASE = os.environ.get("KEY49_OUTPUT_DIR", "xml_downloads")
COMPANIES_CONFIG = os.environ.get("KEY49_COMPANIES_CONFIG", "config/companies.json")


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the monitoring dashboard (HTML page)."""
    template_path = Path(__file__).parent / "templates" / "dashboard.html"
    if template_path.exists():
        return HTMLResponse(template_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)


@app.get("/api/v1/health")
async def health():
    """Service health check."""
    return {
        "service": "key49-fetch-api",
        "version": "0.6.0",
        "status": "ok",
    }


@app.get("/api/v1/companies")
async def get_companies(api_key: str = Depends(verify_api_key)):
    """List all registered companies."""
    companies = list_companies(COMPANIES_CONFIG)
    return {
        "companies": companies,
        "total": len(companies),
    }


@app.get("/api/v1/documents")
async def get_documents(
    company_id: str = Query(..., description="Company/RUC identifier"),
    year: int = Query(..., ge=2000, le=2099, description="Year (YYYY)"),
    month: int = Query(..., ge=1, le=12, description="Month (1-12)"),
    type: Optional[int] = Query(None, ge=1, le=99, description="Document type filter (1=Factura, 6=Retención, etc.)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    api_key: str = Depends(verify_api_key),
):
    """List documents matching the given filters.

    Documents are scanned from the filesystem. Returns paginated results
    with metadata extracted from SRI access keys.
    """
    all_docs = scan_documents(
        base_dir=OUTPUT_BASE,
        company_id=company_id,
        year=year,
        month=month,
        doc_type=type,
    )

    total = len(all_docs)

    # Pagination
    start = (page - 1) * page_size
    end = start + page_size
    paged = all_docs[start:end]

    return {
        "company_id": company_id,
        "year": year,
        "month": month,
        "type": type,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "documents": paged,
    }


@app.get("/api/v1/documents/{access_key}")
async def download_document(
    access_key: str,
    company_id: str = Query(..., description="Company/RUC identifier"),
    year: int = Query(..., ge=2000, le=2099, description="Year (YYYY)"),
    month: int = Query(..., ge=1, le=12, description="Month (1-12)"),
    type: int = Query(..., ge=1, le=99, description="Document type"),
    format: str = Query("xml", regex="^(xml|pdf)$", description="File format: xml or pdf"),
    api_key: str = Depends(verify_api_key),
):
    """Download a specific document file (XML or PDF).

    Returns the file directly with appropriate Content-Type header.
    """
    from src.api.documents import TIPO_MAP

    month_str = f"{month:02d}"
    type_str = f"{type:02d}"
    file_path = (
        Path(OUTPUT_BASE) / company_id / month_str / type_str / f"{access_key}.{format}"
    )

    if not file_path.exists():
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"File not found: {access_key}.{format}",
        )

    content_type = "application/xml" if format == "xml" else "application/pdf"
    tipo_name = TIPO_MAP.get(type_str, f"Type {type_str}")

    return FileResponse(
        path=str(file_path),
        media_type=content_type,
        filename=f"{access_key}.{format}",
        headers={
            "X-Document-Type": tipo_name,
            "X-Document-Access-Key": access_key,
        },
    )


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main():
    """Run the API server via uvicorn."""
    import uvicorn

    host = os.environ.get("KEY49_API_HOST", "0.0.0.0")
    port = int(os.environ.get("KEY49_API_PORT", "8081"))
    reload = os.environ.get("KEY49_API_RELOAD", "").lower() in ("1", "true", "yes")

    uvicorn.run(
        "src.api.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
