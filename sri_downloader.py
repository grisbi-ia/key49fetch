#!/usr/bin/env python3
"""
SRI Ecuador — Descargador de XMLs de Comprobantes Electrónicos Recibidos.

Flujo (basado en análisis HAR de srienlinea.sri.gob.ec):
  1. Navegador stealth abre sesión con token de autenticación.
  2. Llena formulario de búsqueda (año, mes, día, tipo comprobante).
  3. Hace clic en "Buscar"; reCAPTCHA Enterprise invisible se resuelve vía JS.
  4. Espera la tabla de resultados.
  5. Extrae ViewState + cookies del navegador.
  6. Descarga cada XML vía HTTP directo (POST con frmPrincipal:tablaCompRecibidos:N:lnkXml).

Requisitos:
    pip install scrapling playwright httpx
    playwright install chromium
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import sys
import time
from pathlib import Path

import httpx  # noqa: F401 — kept for potential future use
from playwright.async_api import async_playwright
from scrapling import Adaptor  # noqa: F401

# ─── Constantes extraídas del HAR ────────────────────────────────────────────
BASE_URL = "https://srienlinea.sri.gob.ec/comprobantes-electronicos-internet"
LOGIN_URL = f"{BASE_URL}/pages/consultas/recibidos/j_security_check"
PAGE_URL = f"{BASE_URL}/pages/consultas/recibidos/comprobantesRecibidos.jsf"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
)

# Tipos de comprobante (valores del <select> del HAR)
TIPO_COMPROBANTE = {
    1: "Factura",
    4: "Nota de Crédito",
    5: "Nota de Débito",
    6: "Guía de Remisión",
    7: "Comprobante de Retención",
}


# ─── Utilidades ──────────────────────────────────────────────────────────────

def human_delay(min_s: float = 2.0, max_s: float = 5.0):
    """Pausa aleatoria para simular tiempo de lectura humana."""
    delay = random.uniform(min_s, max_s)
    print(f"  ⏳ Pausa humana: {delay:.1f}s...")
    time.sleep(delay)


def get_view_state(html: str) -> str:
    """Extrae javax.faces.ViewState del HTML usando scrapling.Adaptor."""
    adaptor = Adaptor(html, auto_match=False)
    vs_input = adaptor.css_first('input[name="javax.faces.ViewState"]')
    if vs_input:
        value = vs_input.attrib.get("value", "")
        if value:
            return value

    # Fallback: regex sobre el HTML crudo
    match = re.search(
        r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', html
    )
    if match:
        return match.group(1)

    raise RuntimeError("No se pudo extraer javax.faces.ViewState del HTML")


def parse_comprobantes(html: str) -> list[dict]:
    """
    Parsea la tabla de comprobantes recibidos y devuelve una lista de dicts
    con índice de fila, datos del comprobante, y nombre del parámetro de descarga.
    """
    adaptor = Adaptor(html, auto_match=False)
    rows = adaptor.css("#frmPrincipal\\:tablaCompRecibidos tbody tr")

    if not rows:
        # Fallback: buscar en cualquier tabla con role=grid
        rows = adaptor.css("table[role='grid'] tbody tr[class*='rf-dt-r']")

    comprobantes = []
    for i, row in enumerate(rows):
        cols = row.css("td")
        if len(cols) < 10:
            continue

        # Extraer clave de acceso (49 dígitos) de la fila
        row_text = row.text or ""
        clave_match = re.search(r"(\d{49})", row_text)
        clave = clave_match.group(1) if clave_match else ""

        # Número del comprobante (primera columna)
        nro = (cols[0].text or "").strip()

        # Emisor (segunda columna, texto resumido)
        emisor_text = (cols[1].text or "").strip()
        emisor = emisor_text[:60] if emisor_text else "desconocido"

        comprobantes.append({
            "index": i,
            "nro": nro,
            "emisor": emisor,
            "clave_acceso": clave,
            "xml_param": f"frmPrincipal:tablaCompRecibidos:{i}:lnkXml",
        })

    return comprobantes


def build_download_form(
    view_state: str,
    ano: int,
    mes: int,
    dia: int,
    tipo_comprobante: int,
    xml_param: str,
) -> dict:
    """
    Construye el cuerpo del POST de descarga XML tal como se observó en el HAR
    (entry 108: POST sin AJAX, respuesta application/xml).
    """
    return {
        "frmPrincipal": "frmPrincipal",
        "frmPrincipal:opciones": "ruc",
        "frmPrincipal:ano": str(ano),
        "frmPrincipal:mes": str(mes),
        "frmPrincipal:dia": str(dia),
        "frmPrincipal:cmbTipoComprobante": str(tipo_comprobante),
        "g-recaptcha-response": "",
        "javax.faces.ViewState": view_state,
        xml_param: xml_param,
    }


# ─── Flujo principal ─────────────────────────────────────────────────────────

async def download_xmls(
    ano: int,
    mes: int,
    dia: int = 0,
    tipo_comprobante: int = 1,
    output_dir: str = "xml_downloads",
    token: str | None = None,
    password: str = "sriclave",
    ruc: str | None = None,
    clave: str | None = None,
):
    """
    Flujo completo: autenticación → búsqueda → descarga de XMLs.

    Args:
        ano:              Año de consulta.
        mes:              Mes de consulta (1-12).
        dia:              Día de consulta (0 = todos los días del mes).
        tipo_comprobante: 1=Factura, 4=N/Crédito, 5=N/Débito, 6=Guía, 7=Retención.
        output_dir:       Carpeta donde guardar los XMLs descargados.
        token:            Token de autenticación (opcional). Si no se provee,
                          se abre el navegador para login manual.
        password:         Contraseña para j_security_check (default: sriclave).
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        # ── Fase 1: Navegador stealth para auth + búsqueda ───────────────
        print("🌐 Iniciando navegador stealth...")
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 768},
            locale="es-EC",
            accept_downloads=True,
        )

        # Inyectar scripts anti-detección de automatización
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['es-ES', 'es', 'en']
            });
            window.chrome = { runtime: {} };
        """)

        page = await context.new_page()

        if token:
            # ── 1a. Login automático con token ───────────────────────────
            print(f"🔑 Autenticando con token: {token[:10]}...")
            await page.goto(PAGE_URL, wait_until="networkidle")
            human_delay(1, 2)

            await page.evaluate(f"""
                (() => {{
                    const form = document.createElement('form');
                    form.method = 'POST';
                    form.action = '{LOGIN_URL}';
                    const fields = {{
                        'j_username': '{token}',
                        'j_password': '{password}',
                        'j_token':    '{token}'
                    }};
                    for (const [k, v] of Object.entries(fields)) {{
                        const input = document.createElement('input');
                        input.type = 'hidden';
                        input.name = k;
                        input.value = v;
                        form.appendChild(input);
                    }}
                    document.body.appendChild(form);
                    form.submit();
                }})();
            """)

            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)
        else:
            # ── 1b. Login manual ──────────────────────────────────────────
            sri_login_url = "https://srienlinea.sri.gob.ec/tuportal-internet/accederAplicacion.jspa?redireccion=60&idGrupo=55"
            print("🔐 Abriendo página del SRI para login manual...")
            await page.goto(sri_login_url, wait_until="networkidle")

            # Auto-rellenar RUC y clave si se proporcionaron
            if ruc or clave:
                human_delay(1, 2)
                # Buscar los campos del formulario de login
                # El portal SRI usa distintos selectores, probamos varios
                ruc_selectors = [
                    'input[name="ruc"]',
                    'input[name="usuario"]',
                    'input[id*="ruc"]',
                    'input[id*="usuario"]',
                    'input[placeholder*="RUC"]',
                    'input[placeholder*="C.I"]',
                    '#usuario',
                    '#ruc',
                ]
                clave_selectors = [
                    'input[name="password"]',
                    'input[name="clave"]',
                    'input[type="password"]',
                    'input[id*="clave"]',
                    'input[id*="password"]',
                    '#password',
                    '#clave',
                ]

                if ruc:
                    for sel in ruc_selectors:
                        el = await page.query_selector(sel)
                        if el:
                            await el.click()
                            await el.fill(ruc)
                            print(f"   ✅ RUC rellenado: {ruc}")
                            break
                    else:
                        print(f"   ⚠️  No se encontró el campo de RUC. Escríbelo manualmente.")

                human_delay(0.5, 1)

                if clave:
                    for sel in clave_selectors:
                        el = await page.query_selector(sel)
                        if el:
                            await el.click()
                            await el.fill(clave)
                            print("   ✅ Clave rellenada")
                            break
                    else:
                        print("   ⚠️  No se encontró el campo de clave. Escríbela manualmente.")

                print()
                print("👉 Haz clic en 'Ingresar' en el navegador.")
            else:
                print("   Inicia sesión con tu RUC y clave en el navegador.")

            print("   Luego navega a: Facturación Electrónica → Comprobantes recibidos.")
            print()

            # Esperar a que el usuario llegue a la página de comprobantes
            print("   ⏳ Esperando a que llegues a la página de comprobantes recibidos...")
            while True:
                await page.wait_for_timeout(2000)
                url = page.url
                if "comprobantesRecibidos.jsf" in url:
                    break
            await page.wait_for_load_state("networkidle")
            print("   ✅ ¡Login detectado!")

        # Si no estamos en la página de comprobantes, navegar directamente
        current_url = page.url
        if "comprobantesRecibidos.jsf" not in current_url:
            full_url = (
                f"{PAGE_URL}?&contextoMPT="
                "https://srienlinea.sri.gob.ec/tuportal-internet"
            )
            await page.goto(full_url, wait_until="networkidle")
            await page.wait_for_timeout(2000)

        print("📋 Página de búsqueda cargada")

        # ── 2. El usuario hace la búsqueda manualmente ───────────────────
        # reCAPTCHA Enterprise bloquea clics automatizados, así que
        # dejamos que el usuario haga clic en "Consultar" manualmente.
        print()
        print("👉 Ahora haz la búsqueda TÚ en el navegador:")
        print("   1. Verifica año, mes, día y tipo de comprobante.")
        print("   2. Haz clic en 'Consultar'.")
        print("   3. Espera a que aparezca la tabla de resultados.")
        print()
        print("   ⏳ Esperando a que aparezca la tabla de comprobantes...")

        # Polling: esperar a que la tabla de resultados aparezca en el DOM
        while True:
            await page.wait_for_timeout(3000)
            table_rows = await page.query_selector_all(
                "#frmPrincipal\\:tablaCompRecibidos tbody tr"
            )
            if table_rows:
                break
            # Revisar también si hay mensaje "No existen comprobantes"
            page_text = await page.inner_text("body")
            if "No existen comprobantes" in page_text:
                print("❌ No existen comprobantes para los filtros seleccionados.")
                await browser.close()
                return

        print(f"✅ Tabla detectada con {len(table_rows)} filas")

        human_delay(1, 3)

        # ── Función auxiliar: extraer comprobantes del DOM ────────────────
        async def extract_comprobantes_from_page():
            """Extrae la lista de comprobantes de la página actual de la tabla."""
            return await page.evaluate("""
                () => {
                    const rows = document.querySelectorAll(
                        '#frmPrincipal\\\\:tablaCompRecibidos tbody tr'
                    );
                    const results = [];
                    rows.forEach((row, i) => {
                        const cells = row.querySelectorAll('td');
                        if (cells.length < 5) return;

                        const nro = (cells[0] && cells[0].innerText || '').trim();
                        const emisor = (cells[1] && cells[1].innerText || '').trim().substring(0, 60);

                        const rowText = row.innerText || '';
                        const claveMatch = rowText.match(/(\\d{49})/);
                        const clave = claveMatch ? claveMatch[1] : '';

                        const xmlLink = row.querySelector('a[id*="lnkXml"], input[id*="lnkXml"]');
                        const xmlId = xmlLink ? xmlLink.id : '';

                        const pdfLink = row.querySelector('a[id*="lnkPdf"], input[id*="lnkPdf"]');
                        const pdfId = pdfLink ? pdfLink.id : '';

                        results.push({
                            index: i,
                            nro: nro,
                            emisor: emisor,
                            clave_acceso: clave,
                            xml_link_id: xmlId,
                            pdf_link_id: pdfId
                        });
                    });
                    return results;
                }
            """)

        # ── Función auxiliar: descargar archivos de una lista ─────────────
        async def download_comprobantes(comprobantes):
            """Descarga XML y PDF de cada comprobante haciendo clic en sus enlaces."""
            ok = 0
            fail = 0
            for comp in comprobantes:
                clave = comp["clave_acceso"] or f"comprobante_{comp['index']}"
                nro_display = comp['nro'] or '?'

                for fmt, link_key, ext in [("XML", "xml_link_id", ".xml"), ("PDF", "pdf_link_id", ".pdf")]:
                    human_delay(1, 3)

                    link_id = comp.get(link_key, "")
                    filename = f"{clave}{ext}"
                    filepath = out / filename

                    print(f"  📥 [{nro_display}] {filename}...", end=" ", flush=True)

                    if not link_id:
                        print(f"❌ No se encontró enlace {fmt} en la fila")
                        fail += 1
                        continue

                    try:
                        css_id = link_id.replace(":", "\\:")

                        async with page.expect_download(timeout=30000) as download_info:
                            await page.click(f"#{css_id}")

                        download = await download_info.value
                        await download.save_as(str(filepath))

                        size_kb = filepath.stat().st_size / 1024
                        print(f"✅ {size_kb:.1f} KB")
                        ok += 1

                    except Exception as e:
                        print(f"❌ {e}")
                        fail += 1
            return ok, fail

        # ── 3. Recorrer todas las páginas de la tabla ────────────────────
        total_downloaded = 0
        total_errors = 0
        page_num = 1

        while True:
            print(f"\n── Página {page_num} de resultados ──")

            comprobantes = await extract_comprobantes_from_page()
            print(f"📊 Comprobantes en esta página: {len(comprobantes)}")

            if not comprobantes:
                if page_num == 1:
                    print("❌ No se encontraron filas de comprobantes en la tabla.")
                break

            for c in comprobantes:
                clave_display = c["clave_acceso"] or "(sin clave)"
                emisor = c["emisor"] or "desconocido"
                nro = c["nro"] or "?"
                print(f"   #{nro:>3s} │ {emisor:<40s} │ {clave_display}")

            print(f"\n📥 Descargando {len(comprobantes)} comprobantes (XML + PDF)...")
            ok, fail = await download_comprobantes(comprobantes)
            total_downloaded += ok
            total_errors += fail

            # ── Verificar si hay página siguiente ────────────────────────
            next_btn = await page.query_selector(
                ".ui-paginator-next:not(.ui-state-disabled)"
            )
            if not next_btn:
                # No hay más páginas
                break

            print(f"\n➡️  Avanzando a la página {page_num + 1}...")
            await next_btn.click()
            human_delay(2, 4)
            # Esperar a que la tabla se actualice
            await page.wait_for_timeout(3000)
            page_num += 1

        print(f"\n{'─' * 60}")
        print(f"🎉 Descarga completada: {total_downloaded} OK, {total_errors} errores")
        print(f"📁 Archivos guardados en: {out.resolve()}")
        print(f"{'─' * 60}")

        await browser.close()


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Descarga XMLs de comprobantes electrónicos recibidos del SRI Ecuador",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Login manual (sin token) — se abre el navegador para que inicies sesión
  python sri_downloader.py --ano 2026 --mes 1

  # Pre-rellenar RUC y clave (solo haces clic en Ingresar)
  python sri_downloader.py --ruc 0195160252001 --clave MiClave123 --ano 2026 --mes 1

  # Descargar notas de crédito del 15 de marzo
  python sri_downloader.py --ano 2026 --mes 3 --dia 15 --tipo 4

  # Guardar en carpeta específica
  python sri_downloader.py --ano 2026 --mes 1 --output /tmp/mis_xmls

Tipos de comprobante:
  1 = Factura
  4 = Nota de Crédito
  5 = Nota de Débito
  6 = Guía de Remisión
  7 = Comprobante de Retención
        """,
    )
    parser.add_argument(
        "--token", default=None,
        help="Token de autenticación SRI (opcional). Si no se provee, se abre navegador para login manual.",
    )
    parser.add_argument(
        "--password", default="sriclave",
        help="Contraseña para j_security_check (default: sriclave)",
    )
    parser.add_argument("--ano", type=int, required=True, help="Año de consulta")
    parser.add_argument("--mes", type=int, required=True, help="Mes (1-12)")
    parser.add_argument("--dia", type=int, default=0, help="Día (0 = todos)")
    parser.add_argument(
        "--tipo", type=int, default=1,
        help="Tipo comprobante: 1=Factura, 4=NC, 5=ND, 6=Guía, 7=Retención",
    )
    parser.add_argument(
        "--ruc", default=None,
        help="RUC/CI para pre-rellenar en el login (opcional)",
    )
    parser.add_argument(
        "--clave", default=None,
        help="Clave SRI para pre-rellenar en el login (opcional)",
    )
    parser.add_argument(
        "--output", default="xml_downloads", help="Carpeta de salida",
    )

    args = parser.parse_args()

    if not 1 <= args.mes <= 12:
        parser.error("--mes debe estar entre 1 y 12")
    if not 0 <= args.dia <= 31:
        parser.error("--dia debe estar entre 0 y 31")

    asyncio.run(
        download_xmls(
            ano=args.ano,
            mes=args.mes,
            dia=args.dia,
            token=args.token,
            password=args.password,
            ruc=args.ruc,
            clave=args.clave,
            tipo_comprobante=args.tipo,
            output_dir=args.output,
        )
    )


if __name__ == "__main__":
    main()
