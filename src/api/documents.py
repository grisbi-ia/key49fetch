"""Key49-Fetch REST API — Document scanner.

Scans the filesystem for downloaded documents and extracts metadata
from access keys (49-digit SRI clave de acceso).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional


# ─── Access key structure (SRI standard) ─────────────────────────────────────
# Posiciones:  0-1  2-3  4-7  8-9  10-22   23-24 25-36  37-46   47-47  48-48
# Significado: DD   MM   AAAA TIPO EMISOR  AMB   SEC    EMISION DIGITO CHECK
#
# TIPO (positions 8-9):
#   01 = Factura, 02 = Liquidación, 03 = NC, 04 = ND, 06 = Retención
# EMISOR RUC (positions 10-22): 13-digit RUC
# EMISSION DATE (positions 0-7): DDMMAAAA

TIPO_MAP = {
    "01": "Factura",
    "02": "Liquidación de compra",
    "03": "Notas de Crédito",
    "04": "Notas de Débito",
    "06": "Comprobante de Retención",
}


def parse_access_key(access_key: str) -> dict:
    """Extract metadata from a 49-digit SRI access key.

    Args:
        access_key: The 49-digit clave de acceso.

    Returns:
        Dict with emission_date, tipo, tipo_nombre, emisor_ruc.
        Values are None if the key can't be parsed.
    """
    if not access_key or len(access_key) != 49:
        return {
            "emission_date": None,
            "tipo": None,
            "tipo_nombre": None,
            "emisor_ruc": None,
        }

    try:
        day = int(access_key[0:2])
        month = int(access_key[2:4])
        year = int(access_key[4:8])
        emission_date = date(year, month, day)
    except (ValueError, IndexError):
        emission_date = None

    tipo_code = access_key[8:10] if len(access_key) >= 10 else None
    tipo_nombre = TIPO_MAP.get(tipo_code, f"Tipo {tipo_code}" if tipo_code else None)

    emisor_ruc = access_key[10:23] if len(access_key) >= 23 else None

    return {
        "emission_date": emission_date.isoformat() if emission_date else None,
        "tipo": tipo_code,
        "tipo_nombre": tipo_nombre,
        "emisor_ruc": emisor_ruc,
    }


def scan_documents(
    base_dir: str | Path,
    company_id: str,
    year: int,
    month: int,
    doc_type: Optional[int] = None,
) -> list[dict]:
    """Scan the output directory for downloaded documents.

    Args:
        base_dir: Base output directory (e.g., 'xml_downloads').
        company_id: Company/ruc folder name.
        year: Filter by year.
        month: Filter by month (1-12).
        doc_type: Optional filter by document type (1=Factura, etc.).
                  If None, include all types.

    Returns:
        List of document dicts with keys:
        access_key, has_xml, has_pdf, emission_date, emisor_ruc,
        tipo, tipo_nombre, size_xml, size_pdf.
    """
    base = Path(base_dir)
    month_str = f"{month:02d}"
    documents: list[dict] = []

    type_dir_pattern = f"{doc_type:02d}" if doc_type else "*"
    month_path = base / company_id / month_str

    if not month_path.exists():
        return documents

    # If doc_type is specified, scan only that type subdirectory
    type_candidates = sorted(month_path.glob(type_dir_pattern)) if doc_type else sorted(month_path.glob("*"))
    type_candidates = [t for t in type_candidates if t.is_dir() and t.name.isdigit() and len(t.name) == 2]

    for type_dir in type_candidates:
        current_type = int(type_dir.name)
        tipo_name = TIPO_MAP.get(type_dir.name, f"Tipo {type_dir.name}")

        # Group files by access key (strip extension)
        files_by_key: dict[str, dict[str, Path]] = {}
        for f in sorted(type_dir.iterdir()):
            if not f.is_file():
                continue
            key = f.stem  # filename without .xml/.pdf
            if len(key) != 49 or not key.isdigit():
                continue
            if key not in files_by_key:
                files_by_key[key] = {}
            files_by_key[key][f.suffix.lower()] = f

        for access_key, files in files_by_key.items():
            meta = parse_access_key(access_key)

            xml_path = files.get(".xml")
            pdf_path = files.get(".pdf")

            documents.append({
                "access_key": access_key,
                "tipo_code": current_type,
                "tipo_nombre": tipo_name,
                "emission_date": meta.get("emission_date"),
                "emisor_ruc": meta.get("emisor_ruc"),
                "has_xml": xml_path is not None,
                "has_pdf": pdf_path is not None,
                "size_xml": xml_path.stat().st_size if xml_path else None,
                "size_pdf": pdf_path.stat().st_size if pdf_path else None,
            })

    return documents
