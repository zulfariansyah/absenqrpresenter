#!/bin/bash
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$PROJECT_DIR/gunicorn.pid"
PORT=${PORT:-5001}

PID=""
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE" 2>/dev/null)
fi

if [ -z "$PID" ]; then
    PID=$(lsof -ti :$PORT 2>/dev/null | head -n 1)
fi

if [ -n "$PID" ] && (kill -0 "$PID" 2>/dev/null || lsof -i :$PORT >/dev/null 2>&1); then
    echo "🟢 Status: AKTIF / RUNNING (PID: $PID pada Port $PORT)"
    echo ""
    echo "📄 10 Baris Log Terakhir ($PROJECT_DIR/gunicorn.log):"
    tail -n 10 "$PROJECT_DIR/gunicorn.log" 2>/dev/null
    exit 0
fi

echo "🔴 Status: MATI / STOPPED (Tidak sedang berjalan)"
