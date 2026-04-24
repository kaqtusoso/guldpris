#!/bin/bash
# ============================================================
#  setup_local.sh  –  Installerar automatisk bakgrundskörning
#
#  Kör detta EN gång:  bash setup_local.sh
#
#  Det skapar en macOS LaunchAgent som:
#   • Kör guldpris-scrapern varje timme (xx:00)
#   • Fungerar med stängd skärm (displayvila)
#   • Startar automatiskt när du loggar in på datorn
#   • Kör missade körningar nästa gång datorn vaknar
# ============================================================

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_LABEL="se.saljguldet.guldpriser"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
SCRIPT_PATH="$DIR/run_scraper.sh"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   Guldpris-scraper  –  Lokal installation ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Kontrollera att run_scraper.sh finns ─────────────────────────────────────
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "❌  Hittade inte run_scraper.sh i $DIR"
    exit 1
fi

# Gör run_scraper.sh körbar
chmod +x "$SCRIPT_PATH"
echo "✓  run_scraper.sh är körbar"

# ── Skapa LaunchAgents-mappen om den inte finns ───────────────────────────────
mkdir -p "$HOME/Library/LaunchAgents"

# ── Skriv plist-filen ─────────────────────────────────────────────────────────
cat > "$PLIST_PATH" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- Unikt namn för den här bakgrundsuppgiften -->
    <key>Label</key>
    <string>${PLIST_LABEL}</string>

    <!-- Skriptet som körs -->
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${SCRIPT_PATH}</string>
    </array>

    <!-- Schema: kör varje timme på :00 -->
    <key>StartInterval</key>
    <integer>3600</integer>

    <!-- Arbetsmapp -->
    <key>WorkingDirectory</key>
    <string>${DIR}</string>

    <!-- Loggar (stdout och stderr hamnar i samma fil) -->
    <key>StandardOutPath</key>
    <string>${DIR}/scraper.log</string>
    <key>StandardErrorPath</key>
    <string>${DIR}/scraper.log</string>

    <!-- Kör missade körningar när datorn vaknar upp -->
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST_EOF

echo "✓  Plist skapad: $PLIST_PATH"

# ── Avregistrera gammal version (om den finns) ────────────────────────────────
launchctl unload "$PLIST_PATH" 2>/dev/null || true

# ── Registrera LaunchAgent ────────────────────────────────────────────────────
if launchctl load "$PLIST_PATH" 2>/dev/null; then
    echo "✓  LaunchAgent registrerad"
else
    # macOS 13+ använder launchctl bootstrap
    launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || {
        echo "⚠️  Automatisk registrering misslyckades."
        echo "   Prova manuellt: launchctl load $PLIST_PATH"
    }
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅  Klart! Scrapern kör nu automatiskt i bakgrunden."
echo ""
echo "   Schema:  Varje timme (00:00, 01:00, 02:00, ...)"
echo "   JSON:    $DIR/Guldpriser/"
echo "   Logg:    $DIR/scraper.log"
echo ""
echo "Användbara kommandon:"
echo "  Kör nu direkt:    bash $SCRIPT_PATH"
echo "  Visa logg:        tail -f $DIR/scraper.log"
echo "  Kontrollera:      launchctl list | grep saljguldet"
echo "  Stoppa:           launchctl unload $PLIST_PATH"
echo "  Starta om:        launchctl load   $PLIST_PATH"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
