#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# Key49-Fetch — Instalación automatizada (como root, sin sudo)
#   chmod +x install.sh && ./install.sh
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }

[ "$(id -u)" -ne 0 ] && { echo "Ejecutar como ROOT"; exit 1; }

INSTALL_DIR="/opt/key49-fetch"
DATA_DIR="/data/key49-fetch"
REPO_URL="git@github.com:grisbi-ia/key49fetch.git"
API_PORT="8081"

echo "══════════════════════════════════════════════════════════"
echo "  Key49-Fetch — Instalación automatizada v0.6.0"
echo "══════════════════════════════════════════════════════════"

info "Clonando repositorio..."
if [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR" && git pull origin master
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
mkdir -p "$DATA_DIR/xml_downloads"

info "Instalando entorno virtual..."
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

info "Instalando dependencias del sistema..."
apt-get install -y -qq libxcb-shm0 libx11-xcb1 libxrandr2 libxcomposite1 \
    libxcursor1 libxdamage1 libxi6 libxfixes3 libgtk-3-0 \
    libpangocairo-1.0-0 libpango-1.0-0 libatk1.0-0 \
    libcairo-gobject2 libcairo2 libgdk-pixbuf-2.0-0 \
    libxrender1 libasound2 2>/dev/null || true

info "Instalando Firefox..."
.venv/bin/playwright install firefox 2>/dev/null || warn "Firefox no se instaló. Revisa manualmente."

if [ ! -f ".env" ]; then
    FERNET_KEY=$(.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    cat > .env <<EOF
FERNET_KEY=$FERNET_KEY
KEY49_API_PORT=$API_PORT
KEY49_OUTPUT_DIR=$DATA_DIR/xml_downloads
ENABLE_DOCS=1
EOF
    info ".env creado con FERNET_KEY generada"
fi

info "Instalando servicios systemd..."
cp deploy/key49-fetch-api.service /etc/systemd/system/
cp deploy/key49-fetch.service /etc/systemd/system/
cp deploy/key49-fetch.timer /etc/systemd/system/
systemctl daemon-reload

info "Arrancando servicios..."
systemctl enable --now key49-fetch-api.service
systemctl enable --now key49-fetch.timer

# Verificar
sleep 2
curl -s http://localhost:$API_PORT/api/v1/health | python3 -m json.tool 2>/dev/null || warn "API no responde — revisa: systemctl status key49-fetch-api.service"

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  INSTALACIÓN COMPLETA"
echo ""
echo "  API:        http://$(hostname -I | awk '{print $1}'):$API_PORT/"
echo "  Dashboard:  http://$(hostname -I | awk '{print $1}'):$API_PORT/"
echo "  Swagger:    http://$(hostname -I | awk '{print $1}'):$API_PORT/docs"
echo ""
echo "  Próximo paso: editar companies.json y disparar descarga:"
echo "    nano $INSTALL_DIR/config/companies.json"
echo "    curl -X POST http://localhost:$API_PORT/api/v1/fetch?company_id=TU_RUC"
echo "══════════════════════════════════════════════════════════"
