#!/bin/bash
# ============================================================
#  run_api.sh  –  Startar FastAPI-servern som bakgrundstjänst
#
#  Används av macOS LaunchAgent för att hålla API:et igång 24/7.
#  Kör manuellt:  bash run_api.sh
# ============================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/api.log"

# Rotera loggen om den blir för stor (> 2 MB)
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 2097152 ]; then
    mv "$LOG" "$LOG.bak"
fi

echo "" >> "$LOG"
echo "═══════════════════════════════════════" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S')  Startar API-server" >> "$LOG"
echo "═══════════════════════════════════════" >> "$LOG"

# ── Hitta rätt Python ─────────────────────────────────────────────────────────
PYTHON=""

for VENV in "$DIR/venv/bin/python3" "$DIR/.venv/bin/python3"; do
    if [ -x "$VENV" ] && "$VENV" -c "import fastapi, uvicorn" 2>/dev/null; then
        PYTHON="$VENV"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    for BREW_PY in "/opt/homebrew/bin/python3" "/usr/local/bin/python3"; do
        if [ -x "$BREW_PY" ] && "$BREW_PY" -c "import fastapi, uvicorn" 2>/dev/null; then
            PYTHON="$BREW_PY"
            break
        fi
    done
fi

if [ -z "$PYTHON" ]; then
    SYSTEM_PY="$(command -v python3 2>/dev/null)"
    if [ -n "$SYSTEM_PY" ] && "$SYSTEM_PY" -c "import fastapi, uvicorn" 2>/dev/null; then
        PYTHON="$SYSTEM_PY"
    fi
fi

if [ -z "$PYTHON" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S')  FEL: Hittade ingen Python med fastapi/uvicorn!" >> "$LOG"
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S')  Python: $PYTHON" >> "$LOG"

# ── Kör API-servern ───────────────────────────────────────────────────────────
cd "$DIR"
"$PYTHON" -m uvicorn api:app --host 127.0.0.1 --port 8000 >> "$LOG" 2>&1
EXIT_CODE=$?

echo "$(date '+%Y-%m-%d %H:%M:%S')  API avslutades (exit $EXIT_CODE)" >> "$LOG"
exit $EXIT_CODE
