#!/bin/bash
# ============================================================
#  start_api.sh  –  Startar FastAPI-servern lokalt
#
#  Kör:  bash start_api.sh
#
#  API:t lyssnar på http://localhost:8000
#    GET  /priser  →  aktuella guldpriser
#    POST /order   →  skickar orderbekräftelse via e-post
# ============================================================

DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Hitta rätt Python ─────────────────────────────────────────────────────────
PYTHON=""
for candidate in \
    "$DIR/venv/bin/python3" \
    "$DIR/.venv/bin/python3" \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3" \
    "$(command -v python3 2>/dev/null)"; do
    if [ -x "$candidate" ] && "$candidate" -c "import fastapi, uvicorn" 2>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "❌  Hittade ingen Python med fastapi/uvicorn installerat."
    echo "   Kör:  pip3 install -r $DIR/requirements.txt"
    exit 1
fi

# ── Kontrollera .env ──────────────────────────────────────────────────────────
if [ ! -f "$DIR/.env" ]; then
    echo "⚠️  Ingen .env-fil hittades."
    echo "   Kopiera .env.example till .env och fyll i dina nycklar:"
    echo "   cp $DIR/.env.example $DIR/.env"
    echo ""
fi

cd "$DIR"
echo "🚀  Startar API på http://localhost:8000"
echo "   Tryck Ctrl+C för att stänga av."
echo ""

"$PYTHON" -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload
