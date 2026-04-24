#!/bin/bash
# ============================================================
#  setup_permanent.sh  –  Sätter upp permanent drift av Guldkollen API
#
#  Kör detta EN gång:  bash setup_permanent.sh
#
#  Skapar:
#   1. Namngiven Cloudflare-tunnel  →  api.guldkollen.se
#   2. LaunchAgent för API-servern  (håller uvicorn igång 24/7)
#   3. LaunchAgent för cloudflared  (håller tunneln igång 24/7)
#
#  Förutsättningar:
#   • cloudflared installerat (brew install cloudflared)
#   • DNS för guldkollen.se pekar på Cloudflare (marty + romina)
# ============================================================

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
TUNNEL_NAME="guldkollen-api"
HOSTNAME="api.guldkollen.se"
CLOUDFLARED="$(command -v cloudflared || echo /opt/homebrew/bin/cloudflared)"
LAUNCHAGENTS="$HOME/Library/LaunchAgents"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   Guldkollen  –  Permanent driftsättning      ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Steg 1: Logga in på Cloudflare ───────────────────────────────────────────
echo "▶ Steg 1/5: Cloudflare-inloggning"
if [ ! -f "$HOME/.cloudflared/cert.pem" ]; then
    echo "  Öppnar webbläsaren för inloggning..."
    "$CLOUDFLARED" tunnel login
else
    echo "  ✓ Redan inloggad"
fi

# ── Steg 2: Skapa tunnel ──────────────────────────────────────────────────────
echo ""
echo "▶ Steg 2/5: Skapar tunnel '$TUNNEL_NAME'"
if "$CLOUDFLARED" tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"; then
    echo "  ✓ Tunnel finns redan"
else
    "$CLOUDFLARED" tunnel create "$TUNNEL_NAME"
    echo "  ✓ Tunnel skapad"
fi

# Hämta tunnel-ID
TUNNEL_ID=$("$CLOUDFLARED" tunnel list 2>/dev/null | grep "$TUNNEL_NAME" | awk '{print $1}')
echo "  Tunnel-ID: $TUNNEL_ID"

# ── Steg 3: Skapa konfigurationsfil ──────────────────────────────────────────
echo ""
echo "▶ Steg 3/5: Skapar ~/.cloudflared/config.yml"
mkdir -p "$HOME/.cloudflared"

cat > "$HOME/.cloudflared/config.yml" << EOF
tunnel: ${TUNNEL_ID}
credentials-file: ${HOME}/.cloudflared/${TUNNEL_ID}.json

ingress:
  - hostname: ${HOSTNAME}
    service: http://127.0.0.1:8000
  - service: http_status:404
EOF

echo "  ✓ config.yml skapad"

# ── Steg 4: Skapa DNS-post ────────────────────────────────────────────────────
echo ""
echo "▶ Steg 4/5: Skapar DNS-post  $HOSTNAME → tunnel"
"$CLOUDFLARED" tunnel route dns "$TUNNEL_NAME" "$HOSTNAME" 2>/dev/null && \
    echo "  ✓ DNS-post skapad: $HOSTNAME" || \
    echo "  ℹ️  DNS-post finns troligen redan"

# ── Steg 5: Skapa LaunchAgents ────────────────────────────────────────────────
echo ""
echo "▶ Steg 5/5: Installerar LaunchAgents"
mkdir -p "$LAUNCHAGENTS"

chmod +x "$DIR/run_api.sh"
chmod +x "$DIR/run_scraper.sh"

# ── LaunchAgent: API-server ───────────────────────────────────────────────────
API_PLIST="$LAUNCHAGENTS/se.saljguldet.api.plist"
cat > "$API_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>se.saljguldet.api</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${DIR}/run_api.sh</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${DIR}</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${DIR}/api.log</string>
    <key>StandardErrorPath</key>
    <string>${DIR}/api.log</string>

    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
EOF

echo "  ✓ API LaunchAgent skapad"

# ── LaunchAgent: Cloudflare-tunnel ───────────────────────────────────────────
CF_PLIST="$LAUNCHAGENTS/se.saljguldet.cloudflared.plist"
cat > "$CF_PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>se.saljguldet.cloudflared</string>

    <key>ProgramArguments</key>
    <array>
        <string>${CLOUDFLARED}</string>
        <string>tunnel</string>
        <string>run</string>
        <string>${TUNNEL_NAME}</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${DIR}/cloudflared.log</string>
    <key>StandardErrorPath</key>
    <string>${DIR}/cloudflared.log</string>

    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
EOF

echo "  ✓ Cloudflared LaunchAgent skapad"

# ── Ladda LaunchAgents ────────────────────────────────────────────────────────
echo ""
echo "▶ Aktiverar LaunchAgents..."

for PLIST in "$API_PLIST" "$CF_PLIST"; do
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST" 2>/dev/null || \
        launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || \
        echo "  ⚠️  Kunde inte ladda $PLIST – prova: launchctl load $PLIST"
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅  Klart! Guldkollen API körs nu permanent."
echo ""
echo "   API-URL:  https://${HOSTNAME}"
echo "   Logg API:  tail -f ${DIR}/api.log"
echo "   Logg tunnel: tail -f ${DIR}/cloudflared.log"
echo ""
echo "Kontrollera status:"
echo "  launchctl list | grep saljguldet"
echo ""
echo "VIKTIGT: Uppdatera Lovable med den nya URL:en:"
echo "  https://${HOSTNAME}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
