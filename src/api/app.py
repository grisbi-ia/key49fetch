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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from starlette.status import HTTP_404_NOT_FOUND

from src.api.auth import verify_api_key
from src.api.companies import list_companies
from src.api.documents import scan_documents

# Import the core download function (used by background fetch)
from sri_downloader import download_xmls

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

# In-memory store for background fetch jobs (simple dict for single-process)
_fetch_jobs: dict[str, dict] = {}


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


@app.post("/api/v1/fetch")
async def trigger_fetch(
    background_tasks: BackgroundTasks,
    company_id: str = Query(..., description="Company/RUC identifier"),
    year: Optional[int] = Query(None, ge=2000, le=2099, description="Year (default: current)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Month (default: current)"),
    api_key: str = Depends(verify_api_key),
):
    """Trigger an on-demand document download for a specific company/month.

    The download runs in the background. Returns immediately with a job ID.
    Check status via GET /api/v1/fetch/{job_id}.
    """
    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    year = year or now.year
    month = month or now.month

    # Verify company exists and is active
    from src.company_manager import get_company_manager

    try:
        mgr = get_company_manager(COMPANIES_CONFIG)
        company = mgr.get_active(company_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    job_id = str(uuid.uuid4())[:8]
    _fetch_jobs[job_id] = {
        "job_id": job_id,
        "company_id": company_id,
        "ruc": company.ruc,
        "year": year,
        "month": month,
        "status": "pending",
        "created_at": now.isoformat(),
        "result": None,
    }

    background_tasks.add_task(
        _run_fetch_job,
        job_id=job_id,
        company=company,
        year=year,
        month=month,
    )

    return {
        "job_id": job_id,
        "status": "pending",
        "company_id": company_id,
        "ruc": company.ruc,
        "period": f"{year}-{month:02d}",
        "message": f"Download started for {company.business_name} ({year}-{month:02d})",
        "check_status": f"/api/v1/fetch/{job_id}",
    }


@app.get("/api/v1/fetch/{job_id}")
async def get_fetch_status(
    job_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Check the status of a background fetch job."""
    job = _fetch_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job


@app.get("/api/v1/fetch")
async def list_fetch_jobs(
    company_id: Optional[str] = Query(None),
    api_key: str = Depends(verify_api_key),
):
    """List recent fetch jobs, optionally filtered by company."""
    jobs = list(_fetch_jobs.values())
    if company_id:
        jobs = [j for j in jobs if j["company_id"] == company_id]
    # Most recent first
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return {
        "jobs": jobs[:50],  # Last 50
        "total": len(jobs),
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
    format: str = Query("xml", pattern="^(xml|pdf)$", description="File format: xml or pdf"),
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


# ─── Background fetch worker ─────────────────────────────────────────────────


async def _run_fetch_job(
    job_id: str,
    company,
    year: int,
    month: int,
) -> None:
    """Execute a download in the background and update job status."""
    _fetch_jobs[job_id]["status"] = "running"
    _fetch_jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()

    try:
        result = await download_xmls(
            ano=year,
            mes=month,
            tipos_comprobante=company.download_types,
            output_dir=OUTPUT_BASE,
            ruc=company.ruc,
            clave=company.sri_password_encrypted,
            headless=True,
        )

        if result is None:
            result = {"status": "ok", "downloaded": 0, "skipped": 0, "errors": 0}

        _fetch_jobs[job_id]["status"] = "completed"
        _fetch_jobs[job_id]["result"] = result
        _fetch_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

        # Record stats
        from src.stats_tracker import get_stats_tracker
        from datetime import datetime as dt

        stats_tracker = get_stats_tracker()
        start_time = dt.fromisoformat(_fetch_jobs[job_id]["started_at"])
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        stats_tracker.record_run(
            company_id=company.company_id,
            downloaded=result.get("downloaded", 0),
            skipped=result.get("skipped", 0),
            errors=result.get("errors", 0),
            duration=duration,
            period=f"{year}-{month:02d}",
            ruc=company.ruc,
            business_name=company.business_name,
        )

        # Send webhook if configured
        if company.webhook_url and result.get("downloaded", 0) > 0:
            try:
                from src.webhooks.dispatcher import dispatch_webhook
                await dispatch_webhook(
                    url=company.webhook_url,
                    secret=company.webhook_secret or "",
                    company_id=company.company_id,
                    ruc=company.ruc,
                    period=f"{year}-{month:02d}",
                    new_documents=result.get("downloaded", 0),
                    total_documents=result.get("downloaded", 0) + result.get("skipped", 0),
                )
            except Exception:
                pass

    except Exception as e:
        _fetch_jobs[job_id]["status"] = "failed"
        _fetch_jobs[job_id]["error"] = str(e)
        _fetch_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()


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
