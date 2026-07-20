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

# Tipos de comprobante (valores reales del <select> del SRI)
TIPO_COMPROBANTE = {
    1: "Factura",
    2: "Liquidación de compra",
    3: "Notas de Crédito",
    4: "Notas de Débito",
    6: "Comprobante de Retención",
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
    tipos_comprobante: list[int] | None = None,
    output_dir: str = "xml_downloads",
    ruc: str | None = None,
    clave: str | None = None,
    capsolver_key: str | None = None,
    headless: bool = False,
):
    """
    Flujo completo: autenticación → búsqueda → descarga de XMLs/PDFs.

    Args:
        ano:              Año de consulta.
        mes:              Mes de consulta (1-12).
        dia:              Día de consulta (0 = todos los días del mes).
        tipos_comprobante: Lista de tipos: [1,4,5,7]. None = todos.
        output_dir:        Carpeta base. Estructura: {output}/{ruc}/{mes:02d}/{tipo_code}/
        ruc:              RUC/CI para rellenar en el login.
        clave:            Clave SRI para rellenar en el login.
        capsolver_key:    API key de CapSolver para resolver reCAPTCHA.
    """
    if tipos_comprobante is None:
        tipos_comprobante = [1, 2, 3, 4, 6]
    base_out = Path(output_dir)
    ruc_folder = ruc or "sin_ruc"

    async with async_playwright() as p:
        # ── Fase 1: Navegador Firefox con anti-detección (como el bot Node.js) ─
        print("🌐 Iniciando navegador Firefox...")
        browser = await p.firefox.launch(
            headless=headless,
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
            print("   ✅ Hook 'solveViaCapSolver' registrado")

            async def activate_capsolver_interceptor():
                """Parcha grecaptcha.enterprise.execute para usar CapSolver."""
                print("   🎣 Activando interceptor de grecaptcha...")
                await page.evaluate("""
                    async () => {
                        // Esperar a que grecaptcha esté disponible (polling)
                        const waitFor = () => new Promise(resolve => {
                            let attempts = 0;
                            const interval = setInterval(() => {
                                attempts++;
                                if (window.grecaptcha && window.grecaptcha.enterprise) {
                                    clearInterval(interval);
                                    resolve(true);
                                } else if (attempts > 120) {
                                    clearInterval(interval);
                                    resolve(false);
                                }
                            }, 500);
                        });
                        const ready = await waitFor();
                        if (!ready) {
                            console.error('[Interceptor] grecaptcha no disponible tras 60s');
                            return;
                        }
                        const originalExecute = window.grecaptcha.enterprise.execute;
                        window.grecaptcha.enterprise.execute = async function(arg1, arg2) {
                            let siteKey = null;
                            let action = null;
                            if (typeof arg1 === 'string') siteKey = arg1;
                            if (arg2 && arg2.action) action = arg2.action;
                            if (typeof arg1 === 'object' && arg1 !== null) action = arg1.action;
                            console.log('[Interceptor] Ejecutando via CapSolver. Action:', action);
                            const token = await window.solveViaCapSolver(siteKey || '', action || 'consulta_cel_recibidos');
                            if (token && typeof token === 'string') {
                                const hidden = document.getElementById('g-recaptcha-response')
                                    || document.querySelector('textarea[name="g-recaptcha-response"]');
                                if (hidden) {
                                    hidden.value = token;
                                    hidden.dispatchEvent(new Event('input', { bubbles: true }));
                                    hidden.dispatchEvent(new Event('change', { bubbles: true }));
                                }
                                if (typeof window.onSubmit === 'function') window.onSubmit();
                                else if (typeof window.rcBuscar === 'function') window.rcBuscar();
                                return token;
                            }
                            console.warn('[Interceptor] CapSolver falló, usando original');
                            return originalExecute.apply(this, arguments);
                        };
                        console.log('[Interceptor] grecaptcha.enterprise.execute PARCHADO con CapSolver');
                    }
                """)
                print("   ✅ Interceptor activado")

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

            # Esperar activamente a que termine la redirección Keycloak → SRI
            print("   ⏳ Esperando redirección post-login...")
            for _ in range(30):  # hasta 90s
                await page.wait_for_timeout(3000)
                url = page.url
                # Keycloak URLs have /auth/realms/ — we need to be PAST that
                if "/auth/realms/" in url:
                    continue
                if "sri-en-linea" in url or "tuportal-internet" in url:
                    break
            await page.wait_for_load_state("networkidle")
            print(f"   ✅ Login completado → {page.url[-80:]}")
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

        grand_total_downloaded = 0
        grand_total_errors = 0
        grand_total_skipped = 0

        for tipo_idx, tipo_comprobante in enumerate(tipos_comprobante):
            tipo_nombre = TIPO_COMPROBANTE.get(tipo_comprobante, str(tipo_comprobante))
            tipo_code = f"{tipo_comprobante:02d}"
            out = base_out / ruc_folder / f"{mes:02d}" / tipo_code
            out.mkdir(parents=True, exist_ok=True)

            print(f"\n{'═' * 60}")
            print(f"📋 Tipo {tipo_idx + 1}/{len(tipos_comprobante)}: {tipo_nombre} (código {tipo_code})")
            print(f"📁 Destino: {out}")
            print(f"{'═' * 60}")

            # ── Navegar a Comprobantes Recibidos (vía menú — como humano) ─
            print("📂 Navegando a Comprobantes Electrónicos Recibidos...")
            # Ir directo a la página de comprobantes (sin pasar por perfil — evita pérdida de sesión)
            COMPROBANTES_URL = (
                "https://srienlinea.sri.gob.ec/comprobantes-electronicos-internet/"
                "pages/consultas/recibidos/comprobantesRecibidos.jsf"
            )
            await page.goto(COMPROBANTES_URL, wait_until="domcontentloaded", timeout=45000)
            human_delay(3, 5)

            # Si la sesión expiró, Keycloak redirige al login.
            # En ese caso, ir por el menú tradicional.
            if "auth/realms" in page.url or "openid-connect" in page.url:
                print("   🔄 Sesión no detectada, navegando por menú tradicional...")
                await page.goto(
                    "https://srienlinea.sri.gob.ec/sri-en-linea/contribuyente/perfil",
                    wait_until="domcontentloaded", timeout=45000
                )
                human_delay(2, 4)
                MODULE_URL = (
                    "https://srienlinea.sri.gob.ec/tuportal-internet/"
                    "accederAplicacion.jspa?redireccion=57&idGrupo=55"
                )
                await page.goto(MODULE_URL, wait_until="domcontentloaded", timeout=45000)
                human_delay(3, 5)
            
            # Verificar si hay página intermedia de redirección (j_security_check)
            try:
                redirect_form = await page.query_selector('form[action*="j_security_check"]')
                if redirect_form:
                    print("   🔄 Detectada página de redirección, esperando...")
                    await page.wait_for_url(
                        lambda url: "comprobantes-electronicos" in url,
                        timeout=30000
                    )
                    human_delay(2, 3)
            except Exception:
                pass
            
            # Scroll natural para "ver" la página
            for _ in range(random.randint(2, 4)):
                await page.mouse.wheel(0, random.randint(100, 400))
                await page.wait_for_timeout(random.randint(200, 600))
            
            print(f"   🔗 URL final: {page.url}")
            print("📋 Página de búsqueda cargada")

            # ── Esperar a que el formulario JSF esté realmente listo ──
            try:
                await page.wait_for_selector(
                    'select[id*="ano"]',
                    timeout=15000
                )
                print("   ✅ Formulario JSF detectado")
            except Exception:
                print("   ⚠️  Formulario JSF no detectado — intentando navegación directa...")
                # Fallback: ir directo a la página de comprobantes recibidos
                DIRECT_URL = (
                    "https://srienlinea.sri.gob.ec/comprobantes-electronicos-internet/"
                    "pages/consultas/recibidos/comprobantesRecibidos.jsf"
                )
                await page.goto(DIRECT_URL, wait_until="domcontentloaded", timeout=30000)
                human_delay(3, 5)
                try:
                    await page.wait_for_selector('select[id*="ano"]', timeout=10000)
                    print("   ✅ Formulario JSF detectado (vía directa)")
                except Exception:
                    page_text = await page.inner_text("body")
                    print(f"   🔍 Contenido (primeros 300 chars): {page_text[:300]}")

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

            # Seleccionar tipo de comprobante (fuzzy text match, como el bot Node.js)
            tipo_nombre = TIPO_COMPROBANTE.get(tipo_comprobante, str(tipo_comprobante))
            tipo_select_value = await page.evaluate("""
                (searchText) => {
                    // Try by exact ID first
                    let sel = document.getElementById('frmPrincipal:cmbTipoComprobante');
                    // Fallback: any select with TipoComprobante in ID or name
                    if (!sel) {
                        const selects = document.querySelectorAll('select');
                        for (const s of selects) {
                            if ((s.id || '').toUpperCase().includes('TIPO') ||
                                (s.name || '').toUpperCase().includes('TIPO')) {
                                sel = s;
                                break;
                            }
                        }
                    }
                    // Last resort: any select with matching options
                    if (!sel) {
                        const selects = document.querySelectorAll('select');
                        for (const s of selects) {
                            for (let i = 0; i < s.options.length; i++) {
                                if (s.options[i].text.toUpperCase().includes(searchText)) {
                                    sel = s;
                                    break;
                                }
                            }
                            if (sel) break;
                        }
                    }
                    if (!sel) return null;
                    const upper = searchText.toUpperCase();
                    for (let i = 0; i < sel.options.length; i++) {
                        if (sel.options[i].text.toUpperCase().includes(upper)) {
                            return sel.options[i].value;
                        }
                    }
                    return null;
                }
            """, tipo_nombre.upper())
            if tipo_select_value:
                await page.select_option(
                    '#frmPrincipal\\:cmbTipoComprobante', tipo_select_value
                )
                print(f"   ✅ Tipo: {tipo_nombre} (valor select: {tipo_select_value})")
            else:
                # Debug: mostrar todos los selects disponibles
                selects_debug = await page.evaluate("""
                    () => {
                        const selects = document.querySelectorAll('select');
                        const info = [];
                        for (const s of selects) {
                            const options = [];
                            for (let i = 0; i < Math.min(s.options.length, 5); i++) {
                                options.push(s.options[i].text.trim());
                            }
                            info.push({
                                id: s.id || '(sin id)',
                                name: s.name || '(sin name)',
                                options: options
                            });
                        }
                        return info;
                    }
                """)
                print(f"   🔍 Selects en la página: {selects_debug}")
                print(f"   ❌ No se encontró opción para '{tipo_nombre}' en el select")
                continue
            human_delay(1, 2)

            # ── Función auxiliar: click humano en botón ────
            async def human_click(locator_sel, label="botón"):
                """Busca el elemento y hace clic con movimiento de mouse natural."""
                btn = await page.query_selector(locator_sel)
                if not btn:
                    return False
                await btn.scroll_into_view_if_needed()
                await page.wait_for_timeout(random.randint(200, 500))
                box = await btn.bounding_box()
                if box:
                    # Mover mouse desde una posición aleatoria hacia el botón
                    vp = page.viewport_size
                    start_x = random.randint(50, (vp["width"] or 800) - 50)
                    start_y = random.randint(50, (vp["height"] or 600) - 50)
                    await page.mouse.move(start_x, start_y)
                    await page.wait_for_timeout(random.randint(30, 100))
                    # Mover hacia el botón en pasos
                    await page.mouse.move(
                        box["x"] + box["width"] * random.uniform(0.3, 0.7),
                        box["y"] + box["height"] * random.uniform(0.3, 0.7),
                        steps=random.randint(4, 8),
                    )
                    await page.wait_for_timeout(random.randint(100, 300))
                await btn.click(delay=random.randint(80, 250))
                print(f"   ✅ Click humano en {label}")
                return True

            # ── Función auxiliar: llenar formulario + humanizar + click ────
            async def fill_and_submit():
                """Llena el formulario con interacción humana y hace click en Buscar."""
                # Scroll inicial para "orientarse" en la página
                for _ in range(random.randint(2, 3)):
                    await page.mouse.wheel(0, random.randint(80, 300))
                    await page.wait_for_timeout(random.randint(150, 400))
                
                for sel, val in [
                    ('#frmPrincipal\\:ano, select[id*="ano"]', str(ano)),
                    ('#frmPrincipal\\:mes, select[id*="mes"]', str(mes)),
                    ('#frmPrincipal\\:dia, select[id*="dia"]', str(dia)),
                    ('#frmPrincipal\\:cmbTipoComprobante, select[id*="TipoComprobante"]', tipo_select_value),
                ]:
                    el = await page.query_selector(sel)
                    if el:
                        # Scroll hasta el elemento
                        await el.scroll_into_view_if_needed()
                        await page.wait_for_timeout(random.randint(150, 400))
                        # Mover mouse al elemento antes de interactuar
                        box = await el.bounding_box()
                        if box:
                            await page.mouse.move(
                                box["x"] + box["width"] * random.uniform(0.2, 0.8),
                                box["y"] + box["height"] * random.uniform(0.2, 0.8),
                                steps=random.randint(2, 5),
                            )
                            await page.wait_for_timeout(random.randint(50, 200))
                        await el.select_option(val)
                        human_delay(0.5, 1.2)

                # Humanización completa antes del click final
                await humanize_page(page)
                human_delay(2, 4)

                # Click en Buscar/Consultar con movimiento humano
                clicked = await human_click(
                    'button[id*="btnBuscar"], button[id*="btnConsultar"]',
                    "Buscar/Consultar"
                )
                if not clicked:
                    # Fallback: buscar span con texto
                    fallback = page.locator('span.ui-button-text').filter(
                        has_text=re.compile(r'Consultar|Buscar')
                    ).first
                    if await fallback.count() > 0:
                        await fallback.hover()
                        await page.wait_for_timeout(random.randint(100, 300))
                        await fallback.click(delay=random.randint(80, 250))
                        print("   ✅ Click (fallback) en Buscar/Consultar")
                    else:
                        print("   ⚠️  No se encontró botón de búsqueda")

            async def reload_and_fill():
                """Recarga la página de comprobantes y re-llena el formulario."""
                # Ir directo a la página de comprobantes
                await page.goto(
                    "https://srienlinea.sri.gob.ec/comprobantes-electronicos-internet/"
                    "pages/consultas/recibidos/comprobantesRecibidos.jsf",
                    wait_until="domcontentloaded", timeout=45000
                )
                human_delay(3, 5)
                # Si volvió al login, intentar por menú
                if "auth/realms" in page.url or "openid-connect" in page.url:
                    await page.goto(
                        "https://srienlinea.sri.gob.ec/sri-en-linea/contribuyente/perfil",
                        wait_until="domcontentloaded", timeout=30000
                    )
                    human_delay(2, 3)
                    await page.goto(
                        "https://srienlinea.sri.gob.ec/tuportal-internet/accederAplicacion.jspa?redireccion=57&idGrupo=55",
                        wait_until="domcontentloaded", timeout=45000
                    )
                    human_delay(3, 5)
                # Scroll natural
                for _ in range(random.randint(1, 3)):
                    await page.mouse.wheel(0, random.randint(80, 300))
                    await page.wait_for_timeout(random.randint(100, 400))
                await fill_and_submit()

            # ── ESTRATEGIA: Comportamiento 100% humano ─
            print("🦄 Iniciando interacción humana con el SRI...")
            print("   🖱️  Movimientos de mouse, scrolls, y delays naturales...")
            await fill_and_submit()

            # ── Esperar tabla de resultados (con reintentos por timeout y captcha) ─
            max_retries = 5
            retry_count = 0
            table_rows = None
            no_comprobantes = False

            while retry_count <= max_retries:
                print("   ⏳ Esperando tabla de comprobantes...")
                got_result = False

                for wait_cycle in range(20):  # máx 60s
                    await page.wait_for_timeout(3000)

                    table_rows = await page.query_selector_all(
                        "#frmPrincipal\\:tablaCompRecibidos tbody tr"
                    )
                    if table_rows:
                        got_result = True
                        break

                    page_text = await page.inner_text("body")

                    # Debug: mostrar fragmento relevante si hay mensaje de error
                    if any(kw in page_text.lower() for kw in ["captcha", "error", "incorrecta", "incorrecto"]):
                        for line in page_text.split("\n"):
                            line_s = line.strip()
                            if line_s and any(kw in line_s.lower() for kw in ["captcha", "error", "incorrecta", "incorrecto"]):
                                print(f"   🔴 [SRI Mensaje] {line_s[:120]}")

                    # Error de captcha
                    if "aptcha" in page_text and ("incorrecto" in page_text.lower() or "incorrecta" in page_text.lower()):
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
                        break  # Sale del for → reintenta abajo

                    if "No existen comprobantes" in page_text or "No existen datos" in page_text:
                        print("⏭️  No existen comprobantes para este tipo.")
                        no_comprobantes = True
                        got_result = True
                        break

                if got_result:
                    break

                # ── Sin resultado: timeout del SRI o captcha rechazado → reintentar ─
                retry_count += 1
                if retry_count > max_retries:
                    print(f"   ❌ Agotados {max_retries} reintentos.")
                    break

                wait_secs = 5 + retry_count * 5  # Backoff más agresivo
                reason = "SRI no respondió (timeout)" if not any(
                    kw in (page_text if 'page_text' in dir() else "")
                    for kw in ["aptcha"]
                ) else "reCAPTCHA rechazado"
                print(f"   ⚠️  {reason} (intento {retry_count}/{max_retries}).")
                print(f"   🕐 Esperando {wait_secs}s para simular pausa humana...")
                await page.wait_for_timeout(wait_secs * 1000)
                # Recargar vía menú y reintentar (comportamiento humano)
                await reload_and_fill()

            if no_comprobantes or not table_rows:
                continue

            print(f"✅ Tabla detectada con {len(table_rows)} filas")

            human_delay(1, 3)

            # ── Extraer sesión del browser para descargas HTTP directas ──
            print("🔑 Extrayendo sesión del navegador (cookies + ViewState)...")
            cookies_list = await context.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies_list)

            view_state = await page.input_value('[name="javax.faces.ViewState"]')
            browser_ua = await page.evaluate("navigator.userAgent")
            current_page_url = page.url.split("?")[0]  # URL sin query params

            print(f"   ✅ Cookies: {len(cookies_list)} | ViewState: {len(view_state)} chars")

            # ── Headers y cliente HTTP persistente ───────────────────────
            http_headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": cookie_str,
                "User-Agent": browser_ua,
                "Host": "srienlinea.sri.gob.ec",
                "Origin": "https://srienlinea.sri.gob.ec",
                "Referer": current_page_url,
            }

            DOWNLOAD_CONCURRENCY = 3
            sem = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)

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

            # ── Descargar un archivo individual via HTTP directo ─────────────
            async def download_file_http(
                client: httpx.AsyncClient, btn_id: str, filepath: Path, label: str
            ) -> bool:
                """POST al JSF con el btn_id para disparar la descarga."""
                max_download_retries = 5
                for attempt in range(1, max_download_retries + 1):
                    async with sem:
                        # Delay aleatorio antes de cada request (200-700ms)
                        delay_ms = random.randint(200, 700)
                        await asyncio.sleep(delay_ms / 1000)

                        form_data = {
                            "frmPrincipal": "frmPrincipal",
                            "frmPrincipal:opciones": "ruc",
                            "frmPrincipal:ano": str(ano),
                            "frmPrincipal:mes": str(mes),
                            "frmPrincipal:dia": str(dia),
                            "frmPrincipal:cmbTipoComprobante": tipo_select_value,
                            "g-recaptcha-response": "",
                            "javax.faces.ViewState": view_state,
                            btn_id: btn_id,
                        }
                        try:
                            resp = await client.post(
                                current_page_url, data=form_data, headers=http_headers
                            )
                            content_type = resp.headers.get("content-type", "")
                            if "html" in content_type or resp.status_code != 200:
                                if attempt < max_download_retries:
                                    await asyncio.sleep(1)
                                    continue
                                print(f"  ❌ {label} — respuesta HTML/error ({resp.status_code})")
                                return False
                            if len(resp.content) == 0:
                                if attempt < max_download_retries:
                                    await asyncio.sleep(1)
                                    continue
                                print(f"  ❌ {label} — respuesta vacía")
                                return False

                            filepath.write_bytes(resp.content)
                            size_kb = len(resp.content) / 1024
                            retry_note = f" (intento {attempt})" if attempt > 1 else ""
                            print(f"  ✅ {label} ({size_kb:.1f} KB){retry_note}")
                            return True
                        except Exception as e:
                            if attempt < max_download_retries:
                                await asyncio.sleep(1)
                                continue
                            print(f"  ❌ {label} — {e}")
                            return False
                return False

            # ── Descargar lote de comprobantes: XMLs primero, luego PDFs ──
            async def download_comprobantes_http(comprobantes):
                """Descarga XML (prioridad) y PDF de cada comprobante.
                Salta archivos que ya existen en disco. Reintentos extra al final."""
                failed_items = []  # (btn_id, filepath, label) para reintentar
                skipped = 0

                async with httpx.AsyncClient(
                    timeout=120, verify=False, follow_redirects=True
                ) as client:
                    # ── Fase 1: Descargar todos los XMLs ─────────────────
                    xml_tasks = []
                    for comp in comprobantes:
                        clave = comp["clave_acceso"] or f"comprobante_{comp['index']}"
                        nro = comp["nro"] or "?"
                        btn_id = comp.get("xml_link_id", "")
                        if not btn_id:
                            continue
                        filepath = out / f"{clave}.xml"
                        if filepath.exists() and filepath.stat().st_size > 0:
                            skipped += 1
                            continue
                        label = f"[{nro}] {clave}.xml"
                        xml_tasks.append((btn_id, filepath, label))

                    if xml_tasks:
                        xml_results = await asyncio.gather(
                            *[download_file_http(client, b, f, l) for b, f, l in xml_tasks]
                        )
                        for (btn_id, filepath, label), ok in zip(xml_tasks, xml_results):
                            if not ok:
                                failed_items.append((btn_id, filepath, label))

                    # ── Fase 2: Descargar todos los PDFs ─────────────────
                    pdf_tasks = []
                    for comp in comprobantes:
                        clave = comp["clave_acceso"] or f"comprobante_{comp['index']}"
                        nro = comp["nro"] or "?"
                        btn_id = comp.get("pdf_link_id", "")
                        if not btn_id:
                            continue
                        filepath = out / f"{clave}.pdf"
                        if filepath.exists() and filepath.stat().st_size > 0:
                            skipped += 1
                            continue
                        label = f"[{nro}] {clave}.pdf"
                        pdf_tasks.append((btn_id, filepath, label))

                    if pdf_tasks:
                        pdf_results = await asyncio.gather(
                            *[download_file_http(client, b, f, l) for b, f, l in pdf_tasks]
                        )
                        for (btn_id, filepath, label), ok in zip(pdf_tasks, pdf_results):
                            if not ok:
                                failed_items.append((btn_id, filepath, label))

                    # ── Fase 3: Reintentar fallidos (2 rondas extra) ─────
                    for retry_round in range(1, 3):
                        if not failed_items:
                            break
                        print(f"  🔄 Ronda de reintentos {retry_round}: {len(failed_items)} archivos pendientes...")
                        await asyncio.sleep(2)
                        still_failed = []
                        for btn_id, filepath, label in failed_items:
                            ok = await download_file_http(client, btn_id, filepath, label)
                            if not ok:
                                still_failed.append((btn_id, filepath, label))
                        failed_items = still_failed

                total = len(xml_tasks) + len(pdf_tasks)
                fail = len(failed_items)
                ok = total - fail
                return ok, fail, skipped

            # ── 3. Recorrer todas las páginas de la tabla ────────────────────
            total_downloaded = 0
            total_errors = 0
            total_skipped = 0
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

                print(f"\n📥 Procesando {len(comprobantes)} comprobantes (XML + PDF)...")
                ok, fail, skipped = await download_comprobantes_http(comprobantes)
                total_downloaded += ok
                total_errors += fail
                total_skipped += skipped
                if skipped:
                    print(f"  ⏭️  {skipped} archivos ya existían en disco")

                # ── Verificar si hay página siguiente ────────────────────────
                next_btn = await page.query_selector(
                    ".ui-paginator-next:not(.ui-state-disabled)"
                )
                if not next_btn:
                    break

                print(f"\n➡️  Avanzando a la página {page_num + 1}...")
                await next_btn.click()
                human_delay(2, 4)
                await page.wait_for_timeout(3000)

                # Re-extraer ViewState y cookies (JSF los cambia en cada paginación)
                view_state = await page.input_value('[name="javax.faces.ViewState"]')
                cookies_list = await context.cookies()
                cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies_list)
                http_headers["Cookie"] = cookie_str
                print(f"   🔑 Sesión actualizada: ViewState {len(view_state)} chars, Cookies {len(cookies_list)}")

                page_num += 1

            print(f"\n{'─' * 60}")
            print(f"🎉 Descarga completada: {total_downloaded} nuevos, {total_skipped} existentes, {total_errors} errores")
            print(f"📁 Archivos guardados en: {out.resolve()}")
            print(f"{'─' * 60}")

            grand_total_downloaded += total_downloaded
            grand_total_errors += total_errors
            grand_total_skipped += total_skipped

            # ── Reciclar identidad entre tipos: nueva huella digital, misma sesión ─
            if tipo_idx < len(tipos_comprobante) - 1:
                print(f"\n🔄 Cambiando de tipo — reciclando identidad del navegador...")
                await context.close()
                human_delay(3, 6)
                # Nueva identidad aleatoria
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
                # Re-registrar hooks en la nueva página
                page.on("console", _on_console)
                await page.route("**/comprobantesRecibidos**", _log_request)
                page.on("response", lambda resp: asyncio.ensure_future(_log_response(resp)))
                if capsolver_key:
                    browser_ua = await page.evaluate("navigator.userAgent")
                    await page.expose_function("solveViaCapSolver", _solve_via_capsolver)
                    capsolver_ready = True
                print(f"   🦎 Nueva identidad: {chosen_vp['width']}x{chosen_vp['height']}")
                # Re-login
                print("🔐 Re-autenticando en SRI...")
                await page.goto(sri_login_url, wait_until="networkidle", timeout=30000)
                human_delay(1, 3)
                for sel in ruc_selectors:
                    el = await page.query_selector(sel)
                    if el:
                        await el.click()
                        human_delay(0.3, 0.8)
                        await el.fill(ruc)
                        break
                human_delay(0.5, 1.5)
                for sel in clave_selectors:
                    el = await page.query_selector(sel)
                    if el:
                        await el.click()
                        human_delay(0.3, 0.8)
                        await el.fill(clave)
                        break
                human_delay(1, 2)
                for sel in login_btn_selectors:
                    try:
                        btn = await page.query_selector(sel)
                        if btn:
                            await btn.click()
                            break
                    except Exception:
                        continue
                await page.wait_for_load_state("networkidle")
                human_delay(2, 4)
                # Esperar redirección Keycloak → SRI
                for _ in range(30):
                    await page.wait_for_timeout(3000)
                    url = page.url
                    if "/auth/realms/" in url:
                        continue
                    if "sri-en-linea" in url or "tuportal-internet" in url:
                        break
                await page.wait_for_load_state("networkidle")
                print("   ✅ Re-login exitoso")

        print(f"\n{'═' * 60}")
        print(f"🎉 RESUMEN TOTAL: {grand_total_downloaded} nuevos, {grand_total_skipped} existentes, {grand_total_errors} errores")
        print(f"📁 Archivos en: {base_out / ruc_folder}")
        print(f"{'═' * 60}")

        return {
            "status": "failed" if grand_total_errors > 0 and grand_total_downloaded == 0 else (
                "partial" if grand_total_errors > 0 else "ok"
            ),
            "downloaded": grand_total_downloaded,
            "skipped": grand_total_skipped,
            "errors": grand_total_errors,
            "output_dir": str(base_out / ruc_folder),
        }


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
  python sri_downloader.py --ruc 0195160252001 --password MiClave123 --year 2026 --month 1

  # API key por argumento
  python sri_downloader.py --ruc 0195160252001 --password MiClave --capsolver-key CAP-XXXXX --year 2026 --month 1

  # Sin CapSolver (captcha manual)
  python sri_downloader.py --ruc 0195160252001 --password MiClave --year 2026 --month 1

  # Descargar notas de crédito del 15 de marzo
  python sri_downloader.py --ruc 0195160252001 --password MiClave --year 2026 --month 3 --day 15 --types 4

Tipos de comprobante:
  1 = Factura
  2 = Liquidación de compra
  3 = Notas de Crédito
  4 = Notas de Débito
  6 = Comprobante de Retención
        """,
    )
    parser.add_argument("--year", type=int, required=True, help="Año de consulta")
    parser.add_argument("--month", type=int, required=True, help="Mes (1-12)")
    parser.add_argument("--day", type=int, default=0, help="Día (0 = todos)")
    parser.add_argument(
        "--types", type=str, default="1,2,3,4,6", dest="types_comp",
        help="Tipos comprobante separados por coma (default: todos). 1=Factura, 2=Liquidación, 3=NC, 4=ND, 6=Retención",
    )
    parser.add_argument(
        "--ruc", default=None,
        help="RUC/CI para login automático",
    )
    parser.add_argument(
        "--password", default=None,
        help="Clave SRI para login automático",
    )
    parser.add_argument(
        "--capsolver-key", default=None, dest="capsolver_key",
        help="API key de CapSolver (o env CAPSOLVER_API_KEY)",
    )
    parser.add_argument(
        "--output", default="xml_downloads", help="Carpeta de salida",
    )
    parser.add_argument(
        "--visible", action="store_true", default=False,
        help="Mostrar ventana del navegador (por defecto es headless)",
    )

    args = parser.parse_args()

    if not 1 <= args.month <= 12:
        parser.error("--month debe estar entre 1 y 12")
    if not 0 <= args.day <= 31:
        parser.error("--day debe estar entre 0 y 31")

    # Cargar .env y resolver API key: argumento > env > .env
    _load_dotenv()
    capsolver_key = args.capsolver_key or os.environ.get("CAPSOLVER_API_KEY")
    if not capsolver_key:
        print("⚠️  Sin CAPSOLVER_API_KEY — el reCAPTCHA deberá resolverse manualmente.")
        print("   Obtén una en: https://dashboard.capsolver.com/")
        print()

    asyncio.run(
        download_xmls(
            ano=args.year,
            mes=args.month,
            dia=args.day,
            ruc=args.ruc,
            clave=args.password,
            capsolver_key=capsolver_key,
            tipos_comprobante=[int(t.strip()) for t in args.types_comp.split(",")],
            output_dir=args.output,
            headless=not args.visible,
        )
    )


if __name__ == "__main__":
    main()
