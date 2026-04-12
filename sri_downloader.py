#!/usr/bin/env python3
"""
SRI Ecuador — Descargador de XMLs de Comprobantes Electrónicos Recibidos.

Flujo (basado en análisis HAR de srienlinea.sri.gob.ec):
  1. Navegador Chromium inicia sesión automáticamente.
  2. Llena formulario de búsqueda (año, mes, día, tipo comprobante).
  3. Usa CapSolver para resolver reCAPTCHA Enterprise invisible.
  4. Inyecta token y dispara la consulta vía JSF AJAX.
  5. Descarga cada XML/PDF haciendo clic en los enlaces directamente.

Requisitos:
    pip install playwright capsolver
    playwright install chromium

Configuración:
    Crea un archivo .env en el directorio del script:
        CAPSOLVER_API_KEY=tu_api_key_de_capsolver
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import random
import re
import sys
import time
from pathlib import Path

import httpx


def _load_dotenv(path: str = ".env") -> None:
    """Carga variables de un archivo .env al entorno (sin dependencias extra)."""
    env_path = Path(path)
    if not env_path.is_file():
        # Intentar relativo al directorio del script
        env_path = Path(__file__).resolve().parent / path
    if not env_path.is_file():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
from playwright.async_api import async_playwright

# ─── Constantes extraídas del HAR ────────────────────────────────────────────
BASE_URL = "https://srienlinea.sri.gob.ec/comprobantes-electronicos-internet"
LOGIN_URL = f"{BASE_URL}/pages/consultas/recibidos/j_security_check"
PAGE_URL = f"{BASE_URL}/pages/consultas/recibidos/comprobantesRecibidos.jsf"

RECAPTCHA_SITE_KEY = "6LdukTQsAAAAAIcciM4GZq4ibeyplUhmWvlScuQE"
CAPSOLVER_API_URL = "https://api.capsolver.com"

# Tipos de comprobante (valores del <select> del HAR)
TIPO_COMPROBANTE = {
    1: "Factura",
    4: "Nota de Crédito",
    5: "Nota de Débito",
    6: "Guía de Remisión",
    7: "Comprobante de Retención",
}

# ─── Fingerprint: UAs y viewports (replicado de browser.manager.js) ──────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0",
]
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]


# ─── Utilidades ──────────────────────────────────────────────────────────────

def human_delay(min_s: float = 2.0, max_s: float = 5.0):
    """Pausa aleatoria para simular tiempo de lectura humana."""
    delay = random.uniform(min_s, max_s)
    print(f"  ⏳ Pausa humana: {delay:.1f}s...")
    time.sleep(delay)


async def humanize_page(page):
    """Movimientos de mouse y scroll aleatorios (réplica de humanizeEx del bot Node.js)."""
    try:
        vp = page.viewport_size
        if vp:
            steps = random.randint(5, 10)
            for _ in range(steps):
                x = random.randint(0, vp["width"] - 1)
                y = random.randint(0, vp["height"] - 1)
                await page.mouse.move(x, y, steps=5)
                await page.wait_for_timeout(int(100 + random.random() * 200))
            # Small scroll
            await page.mouse.wheel(0, int(100 + random.random() * 200))
            await page.wait_for_timeout(500)
            await page.mouse.wheel(0, int(-50 + random.random() * -100))
    except Exception:
        pass


async def solve_recaptcha_enterprise(
    api_key: str, page_url: str, user_agent: str = "", max_attempts: int = 3
) -> str:
    """
    Usa CapSolver para resolver reCAPTCHA Enterprise v2 invisible.
    Envía pageAction y userAgent (requeridos por el SRI).
    Reintenta hasta max_attempts veces ante fallos transitorios.
    Retorna el token g-recaptcha-response válido.
    """
    last_error = None

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            print(f"🤖 Reintentando CapSolver (intento {attempt}/{max_attempts})...")
        else:
            print("🤖 Solicitando solución de reCAPTCHA a CapSolver...")

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                # 1. Crear tarea
                # Replicado exactamente del bot Node.js (CaptchaService.js)
                # que funciona: V2 Enterprise Invisible con minScore
                task = {
                    "type": "ReCaptchaV2EnterpriseTaskProxyless",
                    "websiteURL": page_url,
                    "websiteKey": RECAPTCHA_SITE_KEY,
                    "pageAction": "consulta_cel_recibidos",
                    "minScore": 0.9,
                    "isEnterprise": True,
                    "isInvisible": True,
                }
                if user_agent:
                    task["userAgent"] = user_agent

                print(f"   📤 [CapSolver] Task payload:")
                print(f"      type={task['type']}  websiteURL={task['websiteURL']}")
                print(f"      websiteKey={task['websiteKey']}  pageAction={task['pageAction']}")
                print(f"      minScore={task.get('minScore')}  isInvisible={task.get('isInvisible')}  isEnterprise={task.get('isEnterprise')}")
                if user_agent:
                    print(f"      userAgent={user_agent[:80]}...")

                create_resp = await client.post(
                    f"{CAPSOLVER_API_URL}/createTask",
                    json={"clientKey": api_key, "task": task},
                )
                create_data = create_resp.json()

                if create_data.get("errorId", 0) != 0:
                    raise RuntimeError(
                        f"CapSolver createTask error: {create_data.get('errorDescription', create_data)}"
                    )

                task_id = create_data["taskId"]
                print(f"   📋 Task ID: {task_id}")

                # 2. Polling por resultado (máx ~120s)
                for i in range(60):
                    await asyncio.sleep(2)
                    result_resp = await client.post(
                        f"{CAPSOLVER_API_URL}/getTaskResult",
                        json={
                            "clientKey": api_key,
                            "taskId": task_id,
                        },
                    )
                    result_data = result_resp.json()

                    status = result_data.get("status")
                    if status == "ready":
                        token = result_data["solution"]["gRecaptchaResponse"]
                        print(f"   ✅ reCAPTCHA resuelto ({len(token)} chars)")
                        print(f"      Token prefix: {token[:40]}...")
                        return token
                    elif status == "failed" or result_data.get("errorId", 0) != 0:
                        err_desc = result_data.get("errorDescription", result_data)
                        raise RuntimeError(f"CapSolver solve failed: {err_desc}")

                    if i % 5 == 4:
                        print(f"   ⏳ Esperando solución... ({(i+1)*2}s)")

                raise RuntimeError("CapSolver timeout: no se obtuvo solución en 120s")

        except RuntimeError as e:
            last_error = e
            print(f"   ⚠️  {e}")
            if attempt < max_attempts:
                await asyncio.sleep(3)

    raise last_error


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
    ruc: str | None = None,
    clave: str | None = None,
    capsolver_key: str | None = None,
):
    """
    Flujo completo: autenticación → búsqueda → descarga de XMLs/PDFs.

    Args:
        ano:              Año de consulta.
        mes:              Mes de consulta (1-12).
        dia:              Día de consulta (0 = todos los días del mes).
        tipo_comprobante: 1=Factura, 4=N/Crédito, 5=N/Débito, 6=Guía, 7=Retención.
        output_dir:       Carpeta donde guardar los archivos.
        ruc:              RUC/CI para rellenar en el login.
        clave:            Clave SRI para rellenar en el login.
        capsolver_key:    API key de CapSolver para resolver reCAPTCHA.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        # ── Fase 1: Navegador Firefox con anti-detección (como el bot Node.js) ─
        print("🌐 Iniciando navegador Firefox...")
        browser = await p.firefox.launch(
            headless=False,
            firefox_user_prefs={
                "network.dns.disableIPv6": True,        # Force IPv4 (mejor reputación reCAPTCHA)
                "browser.privatebrowsing.autostart": False,
            },
        )
        chosen_ua = random.choice(USER_AGENTS)
        chosen_vp = random.choice(VIEWPORTS)
        context = await browser.new_context(
            viewport=chosen_vp,
            user_agent=chosen_ua,
            locale="es-EC",
            timezone_id="America/Guayaquil",
            accept_downloads=True,
            ignore_https_errors=True,
        )
        print(f"   🦎 Identidad: {chosen_vp['width']}x{chosen_vp['height']}")

        # Anti-detección (réplica del bot Node.js: StealthPlugin + addInitScript)
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => false});
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['es-EC', 'es', 'en'],
            });
        """)

        page = await context.new_page()

        # ── Logging: capturar console del navegador ──────────────────
        def _on_console(msg):
            text = msg.text
            # Filtrar ruido de cookies SameSite y CSP
            if "SameSite" in text or "Content-Security-Policy" in text or "Glyph bbox" in text:
                return
            print(f"   🌐 [Browser {msg.type}] {text}")
        page.on("console", _on_console)

        # ── Logging: espiar requests POST al SRI (solo comprobantes) ─
        async def _log_request(route, request):
            if request.method == "POST" and "comprobantesRecibidos" in request.url:
                body = request.post_data or ""
                # Extraer g-recaptcha-response del form data
                token_match = re.search(r'g-recaptcha-response=([^&]*)', body)
                token_val = token_match.group(1) if token_match else "(no encontrado)"
                source_match = re.search(r'javax\.faces\.source=([^&]*)', body)
                source_val = source_match.group(1) if source_match else "(no source)"
                print(f"   📡 [NET] POST → {request.url[-60:]}")
                print(f"      source={source_val}")
                print(f"      g-recaptcha-response={'(vacío)' if not token_val else f'{token_val[:40]}... ({len(token_val)} chars)'}")
                print(f"      body total: {len(body)} chars")
            await route.continue_()

        await page.route("**/comprobantesRecibidos**", _log_request)

        # ── Logging: capturar respuestas del SRI a los POSTs ─────────
        async def _log_response(response):
            if response.request.method == "POST" and "comprobantesRecibidos" in response.url:
                print(f"   📥 [NET] Response {response.status} ← {response.url[-60:]}")
                try:
                    resp_body = await response.text()
                    if "captcha" in resp_body.lower() or "incorrecta" in resp_body.lower():
                        print(f"      ⚠️  Respuesta contiene CAPTCHA error!")
                    if "tablaCompRecibidos" in resp_body and "<tr" in resp_body:
                        print(f"      ✅ Respuesta contiene tabla de resultados")
                    # Mostrar fragmento relevante del XML de respuesta
                    if "<partial-response>" in resp_body:
                        # Extraer mensajes del JSF partial response
                        msg_match = re.search(r'ui-messages-\w+-summary["\']>([^<]+)', resp_body)
                        if msg_match:
                            print(f"      📋 JSF Message: {msg_match.group(1)}")
                        print(f"      (respuesta: {len(resp_body)} chars)")
                except Exception:
                    pass

        page.on("response", lambda resp: asyncio.ensure_future(_log_response(resp)))

        # ── Bridge JS→Python para CapSolver (SOLO se usa en fallback) ─
        # Se registra antes de navegar (requisito de expose_function),
        # pero SOLO se activa el interceptor si la estrategia nativa falla.
        capsolver_ready = False
        if capsolver_key:
            browser_ua = await page.evaluate("navigator.userAgent")

            async def _solve_via_capsolver(site_key: str, action: str) -> str:
                """Llamada desde el JS del navegador cuando se invoca execute."""
                print(f"   🎣 [Hook] Interceptada solicitud de token! Action: {action}")
                token = await solve_recaptcha_enterprise(
                    capsolver_key, PAGE_URL, user_agent=browser_ua
                )
                return token

            await page.expose_function("solveViaCapSolver", _solve_via_capsolver)
            capsolver_ready = True
            print("   ✅ Hook 'solveViaCapSolver' registrado (se usará solo como fallback)")

        # ── 1. Login automático ──────────────────────────────────────
        sri_login_url = "https://srienlinea.sri.gob.ec/tuportal-internet/accederAplicacion.jspa?redireccion=60&idGrupo=55"
        print("🔐 Abriendo página del SRI para login...")
        for _goto_attempt in range(3):
            try:
                await page.goto(sri_login_url, wait_until="networkidle", timeout=30000)
                break
            except Exception as e:
                if _goto_attempt < 2:
                    print(f"⚠️  Conexión fallida ({e.__class__.__name__}), reintentando en 5s...")
                    await asyncio.sleep(5)
                else:
                    raise
        human_delay(1, 3)

        if ruc or clave:
            # Buscar y rellenar campos del formulario de login
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
                        human_delay(0.3, 0.8)
                        await el.fill(ruc)
                        print(f"   ✅ RUC rellenado: {ruc}")
                        break
                else:
                    print("   ⚠️  No se encontró el campo de RUC. Escríbelo manualmente.")

            human_delay(0.5, 1.5)

            if clave:
                for sel in clave_selectors:
                    el = await page.query_selector(sel)
                    if el:
                        await el.click()
                        human_delay(0.3, 0.8)
                        await el.fill(clave)
                        print("   ✅ Clave rellenada")
                        break
                else:
                    print("   ⚠️  No se encontró el campo de clave. Escríbela manualmente.")

            # ── Hacer clic en "Ingresar" automáticamente ─────────────
            human_delay(1, 2)
            login_btn_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Ingresar")',
                'a:has-text("Ingresar")',
                'input[value="Ingresar"]',
                '#kc-login',
            ]
            login_clicked = False
            for sel in login_btn_selectors:
                try:
                    btn = await page.query_selector(sel)
                    if btn:
                        await btn.click()
                        login_clicked = True
                        print("   ✅ Clic en 'Ingresar' realizado")
                        break
                except Exception:
                    continue
            if not login_clicked:
                print("   ⚠️  No se encontró botón de login. Haz clic manualmente.")

            await page.wait_for_load_state("networkidle")
            human_delay(2, 4)
        else:
            print("   Inicia sesión con tu RUC y clave en el navegador.")
            print("   ⏳ Esperando login manual...")
            while True:
                await page.wait_for_timeout(2000)
                url = page.url
                if "tuportal-internet" in url and "accederAplicacion" not in url:
                    break
                if "comprobantesRecibidos.jsf" in url:
                    break
            await page.wait_for_load_state("networkidle")
            print("   ✅ ¡Login detectado!")

        # ── 2. Navegar a Comprobantes Recibidos ──────────────────────
        current_url = page.url
        if "comprobantesRecibidos.jsf" not in current_url:
            print("📂 Navegando a Comprobantes Electrónicos Recibidos...")
            full_url = (
                f"{PAGE_URL}?&contextoMPT="
                "https://srienlinea.sri.gob.ec/tuportal-internet"
            )
            await page.goto(full_url, wait_until="networkidle")
            human_delay(2, 4)

        print("📋 Página de búsqueda cargada")

        # ── 3. Llenar formulario y hacer clic en Consultar ───────────
        # Seleccionar año
        ano_select = await page.query_selector('#frmPrincipal\\:ano, select[id*="ano"]')
        if ano_select:
            await ano_select.select_option(str(ano))
            print(f"   ✅ Año: {ano}")
            human_delay(0.5, 1)

        # Seleccionar mes
        mes_select = await page.query_selector('#frmPrincipal\\:mes, select[id*="mes"]')
        if mes_select:
            await mes_select.select_option(str(mes))
            print(f"   ✅ Mes: {mes}")
            human_delay(0.5, 1)

        # Seleccionar día (0 = Todos)
        dia_select = await page.query_selector('#frmPrincipal\\:dia, select[id*="dia"]')
        if dia_select:
            await dia_select.select_option(str(dia))
            label_dia = "Todos" if dia == 0 else str(dia)
            print(f"   ✅ Día: {label_dia}")
            human_delay(0.5, 1)

        # Seleccionar tipo de comprobante
        tipo_select = await page.query_selector(
            '#frmPrincipal\\:cmbTipoComprobante, select[id*="TipoComprobante"]'
        )
        if tipo_select:
            await tipo_select.select_option(str(tipo_comprobante))
            tipo_nombre = TIPO_COMPROBANTE.get(tipo_comprobante, str(tipo_comprobante))
            print(f"   ✅ Tipo: {tipo_nombre}")
            human_delay(1, 2)

        # ── ESTRATEGIA: Click nativo primero → CapSolver como fallback ─
        # El bot Node.js (sri.controller.js) funciona con "MODO NO-CAPTCHA":
        # NO intercepta grecaptcha.enterprise.execute — deja que Google evalúe
        # el browser nativamente. Solo usa CapSolver si falla.

        # Humanizar antes del clic (como humanizeEx del bot Node.js)
        print("🦄 Humanizando interacción antes de consultar...")
        await humanize_page(page)
        human_delay(1, 2)

        # Click nativo en el botón Buscar/Consultar
        print("🔍 Enviando consulta (modo NATIVO — sin interceptor)...")
        try:
            clicked = await page.evaluate("""
                () => {
                    const btn = document.querySelector('button[id*="btnBuscar"]')
                               || document.querySelector('button[id*="btnConsultar"]');
                    if (btn) { btn.click(); return true; }
                    // Fallback: buscar por texto
                    const spans = Array.from(document.querySelectorAll('span.ui-button-text'));
                    const match = spans.find(s => s.innerText.includes('Consultar') || s.innerText.includes('Buscar'));
                    if (match) { match.click(); return true; }
                    return false;
                }
            """)
            if clicked:
                print("   ✅ Click nativo en botón Buscar/Consultar")
            else:
                # Fallback Playwright
                await page.click('#frmPrincipal\\:btnBuscar')
                print("   ✅ Click Playwright en btnBuscar")
        except Exception as e:
            print(f"   ⚠️  Error al hacer clic: {e}")

        # ── Esperar tabla de resultados ──────────────────────────────
        print("   ⏳ Esperando tabla de comprobantes...")
        interceptor_activated = False
        max_retries = 3 if capsolver_ready else 0
        retry_count = 0
        for wait_cycle in range(20):  # máx 60s
            await page.wait_for_timeout(3000)

            table_rows = await page.query_selector_all(
                "#frmPrincipal\\:tablaCompRecibidos tbody tr"
            )
            if table_rows:
                break

            page_text = await page.inner_text("body")

            # Debug: mostrar fragmento relevante si hay mensaje de error
            if any(kw in page_text.lower() for kw in ["captcha", "error", "incorrecta", "incorrecto"]):
                # Extraer solo las líneas relevantes
                for line in page_text.split("\n"):
                    line_s = line.strip()
                    if line_s and any(kw in line_s.lower() for kw in ["captcha", "error", "incorrecta", "incorrecto"]):
                        print(f"   🔴 [SRI Mensaje] {line_s[:120]}")

            # Error de captcha — reintentar
            if "aptcha" in page_text and ("incorrecto" in page_text.lower() or "incorrecta" in page_text.lower()):
                # Cerrar diálogo de error
                try:
                    alert_ok = await page.query_selector(
                        '.ui-dialog .ui-button, .ui-dialog-buttonpane button, '
                        'button:has-text("Aceptar"), button:has-text("OK")'
                    )
                    if alert_ok:
                        await alert_ok.click()
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass

                if capsolver_ready and retry_count < max_retries:
                    retry_count += 1

                    # FALLBACK: Activar interceptor CapSolver solo en retries
                    if not interceptor_activated:
                        print("   🔄 Estrategia nativa falló. Activando interceptor CapSolver...")
                        await page.evaluate("""
                            async () => {
                                const waitForGrecaptcha = () => new Promise(resolve => {
                                    let attempts = 0;
                                    const interval = setInterval(() => {
                                        attempts++;
                                        if (window.grecaptcha && window.grecaptcha.enterprise) {
                                            clearInterval(interval);
                                            resolve(true);
                                        } else if (attempts > 60) {
                                            clearInterval(interval);
                                            resolve(false);
                                        }
                                    }, 500);
                                });

                                const ready = await waitForGrecaptcha();
                                if (ready) {
                                    window.grecaptcha.enterprise.execute = async (arg1, arg2) => {
                                        let siteKey = typeof arg1 === 'string' ? arg1 : null;
                                        let options = typeof arg1 === 'object' ? arg1 : arg2;
                                        let action = options?.action || 'consulta_cel_recibidos';

                                        console.log('[Interceptor] 🕸️ Caught execute! Action: ' + action);

                                        const token = await window.solveViaCapSolver(
                                            siteKey || '6LdukTQsAAAAAIcciM4GZq4ibeyplUhmWvlScuQE',
                                            action
                                        );

                                        if (token && typeof token === 'string') {
                                            console.log('[Interceptor] ✅ Token: ' + token.substring(0, 10) + '...');

                                            const hidden = document.getElementById('g-recaptcha-response')
                                                || document.querySelector('textarea[name="g-recaptcha-response"]');
                                            if (hidden) {
                                                hidden.value = token;
                                                hidden.dispatchEvent(new Event('input', { bubbles: true }));
                                                hidden.dispatchEvent(new Event('change', { bubbles: true }));
                                            }

                                            if (typeof window.onSubmit === 'function') {
                                                console.log('[Interceptor] 🚀 Triggering window.onSubmit()');
                                                window.onSubmit();
                                            } else if (typeof window.rcBuscar === 'function') {
                                                console.log('[Interceptor] 🚀 Triggering window.rcBuscar()');
                                                window.rcBuscar();
                                            }
                                        }

                                        return token;
                                    };
                                    console.log('[Interceptor] ✅ grecaptcha.enterprise.execute parcheado');
                                } else {
                                    console.warn('[Interceptor] ❌ grecaptcha no apareció tras 30s');
                                }
                            }
                        """)
                        interceptor_activated = True

                    print(f"   ⚠️  Captcha rechazado (intento {retry_count}/{max_retries}). Reintentando con CapSolver...")
                    human_delay(0.5, 1)
                    await page.evaluate("executeRecaptcha('consulta_cel_recibidos')")
                    continue
                elif capsolver_ready:
                    print(f"   ❌ Agotados {max_retries} reintentos de reCAPTCHA.")
                    break
                else:
                    print("   ⚠️  reCAPTCHA rechazó. Haz clic en 'Consultar' manualmente.")

            if "No existen comprobantes" in page_text:
                print("❌ No existen comprobantes para los filtros seleccionados.")
                await browser.close()
                return
        else:
            if not table_rows:
                print("❌ Timeout esperando tabla de comprobantes.")
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


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Descarga XMLs de comprobantes electrónicos recibidos del SRI Ecuador",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Totalmente automático (API key en .env)
  echo 'CAPSOLVER_API_KEY=CAP-XXXXX' > .env
  python sri_downloader.py --ruc 0195160252001 --clave MiClave123 --ano 2026 --mes 1

  # API key por argumento
  python sri_downloader.py --ruc 0195160252001 --clave MiClave --capsolver-key CAP-XXXXX --ano 2026 --mes 1

  # Sin CapSolver (captcha manual)
  python sri_downloader.py --ruc 0195160252001 --clave MiClave --ano 2026 --mes 1

  # Descargar notas de crédito del 15 de marzo
  python sri_downloader.py --ruc 0195160252001 --clave MiClave --ano 2026 --mes 3 --dia 15 --tipo 4

Tipos de comprobante:
  1 = Factura
  4 = Nota de Crédito
  5 = Nota de Débito
  6 = Guía de Remisión
  7 = Comprobante de Retención
        """,
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
        help="RUC/CI para login automático",
    )
    parser.add_argument(
        "--clave", default=None,
        help="Clave SRI para login automático",
    )
    parser.add_argument(
        "--capsolver-key", default=None, dest="capsolver_key",
        help="API key de CapSolver (o env CAPSOLVER_API_KEY)",
    )
    parser.add_argument(
        "--output", default="xml_downloads", help="Carpeta de salida",
    )

    args = parser.parse_args()

    if not 1 <= args.mes <= 12:
        parser.error("--mes debe estar entre 1 y 12")
    if not 0 <= args.dia <= 31:
        parser.error("--dia debe estar entre 0 y 31")

    # Cargar .env y resolver API key: argumento > env > .env
    _load_dotenv()
    capsolver_key = args.capsolver_key or os.environ.get("CAPSOLVER_API_KEY")
    if not capsolver_key:
        print("⚠️  Sin CAPSOLVER_API_KEY — el reCAPTCHA deberá resolverse manualmente.")
        print("   Obtén una en: https://dashboard.capsolver.com/")
        print()

    asyncio.run(
        download_xmls(
            ano=args.ano,
            mes=args.mes,
            dia=args.dia,
            ruc=args.ruc,
            clave=args.clave,
            capsolver_key=capsolver_key,
            tipo_comprobante=args.tipo,
            output_dir=args.output,
        )
    )


if __name__ == "__main__":
    main()
