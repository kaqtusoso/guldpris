#!/bin/bash
# ============================================================
#  fix_python_env.sh  –  Skapar virtual environment för scrapern
#
#  Kör detta EN gång:  bash fix_python_env.sh
# ============================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/venv"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   Guldkollen  –  Skapar Python-miljö          ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Hitta Python 3
PYTHON=""
for PY in /opt/homebrew/bin/python3 /usr/local/bin/python3 $(command -v python3 2>/dev/null); do
    if [ -x "$PY" ]; then
        PYTHON="$PY"
        echo "✓ Hittade Python: $PYTHON"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "❌ Ingen Python 3 hittades! Installera via: brew install python3"
    exit 1
fi

# Skapa virtual environment
echo ""
echo "▶ Skapar virtual environment i $VENV ..."
"$PYTHON" -m venv "$VENV"
echo "✓ Virtual environment skapad"

# Installera paket
echo ""
echo "▶ Installerar Python-paket (kan ta en minut) ..."
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$DIR/requirements.txt" -q
echo "✓ Paket installerade"

# Installera Playwright-browsers
echo ""
echo "▶ Installerar Playwright-browsers ..."
"$VENV/bin/python3" -m playwright install chromium 2>/dev/null && \
    echo "✓ Playwright Chromium installerad" || \
    echo "⚠️  Playwright-installation misslyckades (kan påverka Sefina, WebbGuld m.fl.)"

# Verifiera
echo ""
echo "▶ Verifierar installationen ..."
if "$VENV/bin/python3" -c "import requests, bs4, playwright" 2>/dev/null; then
    echo "✓ Alla paket OK!"
else
    echo "⚠️  Något paket saknas – kontrollera requirements.txt"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅  Klart! Scrapern borde nu fungera automatiskt."
echo "   Testa manuellt:  bash run_scraper.sh"
echo "   Kolla loggen:    tail -f scraper.log"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
