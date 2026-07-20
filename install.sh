#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# Key49-Fetch — Script de instalación automatizada
# Ejecutar como ROOT:
#   chmod +x install.sh && ./install.sh
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

if [ "$(id -u)" -ne 0 ]; then
    error "Este script debe ejecutarse como ROOT"
fi

# ─── Configuración (editar si es necesario) ──────────────────────
SERVICE_USER="app"
INSTALL_DIR="/opt/key49-fetch"
DATA_DIR="/data/key49-fetch"
REPO_URL="git@github.com:grisbi-ia/key49fetch.git"
API_PORT="8081"
FERNET_KEY=""

# ─── 1. Verificar requisitos ────────────────────────────────────
echo "══════════════════════════════════════════════════════════"
echo "  Key49-Fetch — Instalación automatizada v0.6.0"
echo "══════════════════════════════════════════════════════════"
echo ""

command -v python3 >/dev/null 2>&1 || error "Python 3 no encontrado. Instálalo: apt install python3 python3-pip python3-venv"
command -v git >/dev/null 2>&1    || error "Git no encontrado. Instálalo: apt install git"

info "Python $(python3 --version)"
info "Git $(git --version)"

# ─── 2. Crear usuario de servicio ───────────────────────────────
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd -r -s /bin/false "$SERVICE_USER"
    info "Usuario '$SERVICE_USER' creado"
else
    info "Usuario '$SERVICE_USER' ya existe"
fi

# ─── 3. Crear directorios ───────────────────────────────────────
mkdir -p "$DATA_DIR/xml_downloads"
info "Directorio de datos: $DATA_DIR"

# ─── 4. Clonar repositorio ──────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Repositorio ya existe, actualizando..."
    cd "$INSTALL_DIR"
    git pull origin master
else
    info "Clonando repositorio..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ─── 5. Entorno virtual Python ──────────────────────────────────
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    info "Entorno virtual creado"
fi

info "Instalando dependencias Python..."
.venv/bin/pip install --quiet -r requirements.txt

# ─── 6. Instalar navegador Firefox ───────────────────────────────
info "Instalando Firefox para Playwright..."
.venv/bin/playwright install firefox 2>/dev/null || {
    warn "Firefox no se instaló. Intenta manualmente:"
    warn "  cd $INSTALL_DIR"
    warn "  .venv/bin/playwright install-deps firefox"
    warn "  .venv/bin/playwright install firefox"
}

# ─── 7. Configurar .env ─────────────────────────────────────────
if [ ! -f ".env" ]; then
    if [ -z "$FERNET_KEY" ]; then
        FERNET_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    fi
    cat > .env <<EOF
# Key49-Fetch — Environment
FERNET_KEY=$FERNET_KEY
KEY49_API_PORT=$API_PORT
KEY49_OUTPUT_DIR=$DATA_DIR/xml_downloads
ENABLE_DOCS=1
# API_KEYS=tu-api-key-1,tu-api-key-2
# ALERT_WEBHOOK_URL=https://hooks.slack.com/...
# ALERT_THRESHOLD=3
EOF
    info ".env creado con FERNET_KEY generada"
else
    info ".env ya existe, se conserva"
fi

# ─── 8. Ajustar permisos ───────────────────────────────────────
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR" "$DATA_DIR"
info "Permisos ajustados (usuario: $SERVICE_USER)"

# ─── 9. Instalar servicios systemd ──────────────────────────────
sed -i "s|/opt/key49-fetch|$INSTALL_DIR|g" deploy/key49-fetch.service
sed -i "s|/data/key49-fetch|$DATA_DIR|g" deploy/key49-fetch.service
sed -i "s|/opt/key49-fetch|$INSTALL_DIR|g" deploy/key49-fetch-api.service
sed -i "s|/data/key49-fetch|$DATA_DIR|g" deploy/key49-fetch-api.service

cp deploy/key49-fetch.service /etc/systemd/system/
cp deploy/key49-fetch.timer /etc/systemd/system/
cp deploy/key49-fetch-api.service /etc/systemd/system/
systemctl daemon-reload
info "Servicios systemd instalados"

# ─── 10. Activar servicios ──────────────────────────────────────
systemctl enable key49-fetch-api.service
systemctl start key49-fetch-api.service
info "API Gateway iniciada en puerto $API_PORT"

systemctl enable key49-fetch.timer
systemctl start key49-fetch.timer
info "Timer de descargas activado (cada 6h)"

# ─── 11. Verificar ──────────────────────────────────────────────
SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
echo ""
echo "══════════════════════════════════════════════════════════"
echo "  INSTALACIÓN COMPLETA"
echo "══════════════════════════════════════════════════════════"
echo ""
echo "  🌐 API:       http://$SERVER_IP:$API_PORT/"
echo "  📊 Dashboard:  http://$SERVER_IP:$API_PORT/"
echo "  📚 Swagger:   http://$SERVER_IP:$API_PORT/docs"
echo "  📁 Archivos:   $DATA_DIR/xml_downloads"
echo "  📝 Logs:      $INSTALL_DIR/logs/"
echo ""
echo "  ─── PRÓXIMOS PASOS ───"
echo ""
echo "  1. Editar companies.json con tus RUCs:"
echo "     nano $INSTALL_DIR/config/companies.json"
echo ""
echo "  2. Disparar primera descarga para cada RUC:"
echo "     curl -X POST \"http://localhost:$API_PORT/api/v1/fetch?company_id=TU_RUC\""
echo ""
echo "  3. Verificar estado de los jobs:"
echo "     curl \"http://localhost:$API_PORT/api/v1/fetch\""
echo ""
echo "  4. Ver logs:"
echo "     journalctl -u key49-fetch-api.service -f"
echo "     journalctl -u key49-fetch.service -f"
echo ""
echo "  5. Copia de seguridad de FERNET_KEY:"
echo "     cat $INSTALL_DIR/.env | grep FERNET_KEY"
echo "     (guarda esta clave en un lugar seguro)"
echo ""
echo "══════════════════════════════════════════════════════════"
