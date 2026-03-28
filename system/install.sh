#!/usr/bin/env bash
# ============================================================================
# LOCK IN — Installer
# Installs system-level focus lock + behavioral monitor + analytics dashboard
# ============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
ORANGE='\033[0;33m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

[[ $EUID -eq 0 ]] || { echo -e "${RED}Run as root:${NC} sudo bash install.sh"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="/opt/lockin"

echo ""
echo -e "${ORANGE}${BOLD}LOCK IN${NC} — Installing system-level focus lock"
echo ""

# ---- Check core dependencies ----
echo -e "  Checking core dependencies..."
for cmd in iptables dig chattr systemctl sysctl python3; do
    if ! command -v "$cmd" &>/dev/null; then
        echo -e "  ${RED}Missing: $cmd${NC}"
        echo -e "  Install it and re-run this script."
        exit 1
    fi
done
echo -e "  ${GREEN}All core dependencies found${NC}"

# ---- Install Python dependencies ----
echo -e "  Installing Python dependencies..."
REAL_USER="${SUDO_USER:-$USER}"

install_pip_pkg() {
    local pkg="$1"
    # Try as real user first (avoids root pip issues)
    if [[ -n "$REAL_USER" && "$REAL_USER" != "root" ]]; then
        sudo -u "$REAL_USER" python3 -m pip install --break-system-packages -q "$pkg" 2>&1 && return 0
    fi
    # Fallback: install as root
    python3 -m pip install --break-system-packages -q "$pkg" 2>&1 && return 0
    return 1
}

# Flask for dashboard
if python3 -c "import flask" 2>/dev/null; then
    echo -e "  Flask already installed"
else
    install_pip_pkg flask && echo -e "  ${GREEN}Flask installed${NC}" || {
        echo -e "  ${ORANGE}Warning: Could not install Flask. Dashboard won't work.${NC}"
    }
fi

# anthropic SDK (for AI analysis)
if python3 -c "import anthropic" 2>/dev/null; then
    echo -e "  anthropic SDK already installed"
else
    install_pip_pkg anthropic && echo -e "  ${GREEN}anthropic SDK installed${NC}" || {
        echo -e "  ${ORANGE}Warning: Could not install anthropic SDK. AI analysis won't work.${NC}"
    }
fi

echo -e "  ${GREEN}Python dependencies installed${NC}"

# ---- Create directories ----
echo -e "  Creating directories..."
mkdir -p /etc/lockin
mkdir -p /var/lib/lockin/screenshots
mkdir -p "$INSTALL_DIR"

# ---- Install CLI ----
echo -e "  Installing lockin CLI..."
cp "$SCRIPT_DIR/lockin" /usr/local/bin/lockin
chmod 755 /usr/local/bin/lockin

# ---- Install guard daemon ----
echo -e "  Installing lockin-guard..."
cp "$SCRIPT_DIR/lockin-guard" /usr/local/bin/lockin-guard
chmod 755 /usr/local/bin/lockin-guard

# ---- Install systemd service ----
echo -e "  Installing systemd service..."
cp "$SCRIPT_DIR/lockin-guard.service" /etc/systemd/system/lockin-guard.service
systemctl daemon-reload
systemctl enable lockin-guard.service

# ---- Install GUI ----
echo -e "  Installing GUI..."
cp "$PROJECT_DIR/lockin-gui" /usr/local/bin/lockin-gui
chmod 755 /usr/local/bin/lockin-gui

# ---- Install monitor, dashboard, analyzer ----
echo -e "  Installing behavioral monitor..."
cp -r "$PROJECT_DIR/monitor" "$INSTALL_DIR/"

echo -e "  Installing analytics dashboard..."
cp -r "$PROJECT_DIR/dashboard" "$INSTALL_DIR/"

echo -e "  Installing AI analyzer..."
cp -r "$PROJECT_DIR/analyzer" "$INSTALL_DIR/"

# Initialize the database
echo -e "  Initializing monitor database..."
python3 -c "
import sys
sys.path.insert(0, '$INSTALL_DIR')
from monitor import db
db.init_db()
print('  Database initialized at $( echo /var/lib/lockin/monitor.db )')
" 2>/dev/null || echo -e "  ${ORANGE}Warning: Could not initialize DB${NC}"

# ---- Create desktop entry ----
echo -e "  Creating desktop entry..."
REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME=$(eval echo "~$REAL_USER")
DESKTOP_DIR="$REAL_HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/lockin.desktop" <<DESKTOP
[Desktop Entry]
Name=Lock In
Comment=Unbypassable focus lock — block everything except what you choose
Exec=/usr/local/bin/lockin-gui
Icon=preferences-system-time
Type=Application
Categories=Utility;Productivity;
Keywords=focus;timer;block;productivity;lock;
StartupNotify=true
DESKTOP
chown "$REAL_USER:$REAL_USER" "$DESKTOP_DIR/lockin.desktop"

# ---- Set permissions ----
chmod -R 755 "$INSTALL_DIR"
chmod 777 /var/lib/lockin /var/lib/lockin/screenshots

echo ""
echo -e "${GREEN}${BOLD}  Installed successfully.${NC}"
echo ""
echo -e "  ${BOLD}Components:${NC}"
echo -e "    lockin CLI            /usr/local/bin/lockin"
echo -e "    lockin-guard daemon   /usr/local/bin/lockin-guard"
echo -e "    lockin-gui            /usr/local/bin/lockin-gui"
echo -e "    monitor               $INSTALL_DIR/monitor/"
echo -e "    dashboard             $INSTALL_DIR/dashboard/"
echo -e "    analyzer              $INSTALL_DIR/analyzer/"
echo ""
echo -e "  ${BOLD}GUI:${NC}"
echo -e "    Search 'Lock In' in your app launcher, or run: ${BOLD}lockin-gui${NC}"
echo ""
echo -e "  ${BOLD}CLI:${NC}"
echo -e "    sudo lockin start 25 github.com       # 25 min, only github"
echo -e "    lockin status                          # check remaining time"
echo -e "    sudo lockin emergency                  # 10-min cooldown unlock"
echo ""
echo -e "  ${BOLD}Dashboard:${NC}"
echo -e "    Opens automatically during sessions at ${BOLD}http://localhost:9999${NC}"
echo ""
echo -e "  ${DIM}Chrome extension: load the extension/ directory at chrome://extensions${NC}"
echo -e "  ${DIM}AI insights require ANTHROPIC_API_KEY environment variable${NC}"
echo ""
