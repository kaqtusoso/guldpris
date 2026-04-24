#!/bin/bash
# ============================================================
#  run_scraper.sh  –  Kör guldpris-scrapern
#
#  Används av macOS LaunchAgent (setup_local.sh) för att köra
#  scrapern var 4:e timme i bakgrunden.
#
#  Kör manuellt:  bash run_scraper.sh
# ============================================================

# Mappen där det här skriptet ligger
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/scraper.log"

# Rotera loggen om den blir för stor (> 1 MB)
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1048576 ]; then
    mv "$LOG" "$LOG.bak"
fi

echo "" >> "$LOG"
echo "═══════════════════════════════════════" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S')  Startar scraper" >> "$LOG"
echo "═══════════════════════════════════════" >> "$LOG"

# ── Hitta rätt Python (den som har rätt paket installerade) ──────────────────
PYTHON=""

# 1. Virtuell miljö i projektmappen (rekommenderat)
for VENV in "$DIR/venv/bin/python3" "$DIR/.venv/bin/python3"; do
    if [ -x "$VENV" ] && "$VENV" -c "import requests, bs4" 2>/dev/null; then
        PYTHON="$VENV"
        break
    fi
done

# 2. Homebrew Python (Apple Silicon eller Intel)
if [ -z "$PYTHON" ]; then
    for BREW_PY in \
        "/opt/homebrew/bin/python3" \
        "/usr/local/bin/python3"; do
        if [ -x "$BREW_PY" ] && "$BREW_PY" -c "import requests, bs4" 2>/dev/null; then
            PYTHON="$BREW_PY"
            break
        fi
    done
fi

# 3. Sista utväg: systemets python3
if [ -z "$PYTHON" ]; then
    SYSTEM_PY="$(command -v python3 2>/dev/null)"
    if [ -n "$SYSTEM_PY" ] && "$SYSTEM_PY" -c "import requests, bs4" 2>/dev/null; then
        PYTHON="$SYSTEM_PY"
    fi
fi

if [ -z "$PYTHON" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S')  FEL: Hittade ingen Python med rätt paket!" >> "$LOG"
    echo "  Kör detta för att installera:  pip3 install -r $DIR/requirements.txt" >> "$LOG"
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S')  Python: $PYTHON" >> "$LOG"

# ── Kör scrapern ─────────────────────────────────────────────────────────────
cd "$DIR"
"$PYTHON" guldpris_scraper.py >> "$LOG" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S')  Klar! (exit 0)" >> "$LOG"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S')  Avslutade med fel (exit $EXIT_CODE)" >> "$LOG"
fi

exit $EXIT_CODE
