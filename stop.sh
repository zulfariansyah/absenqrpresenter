#!/bin/bash
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$PROJECT_DIR/gunicorn.pid"
PORT=${PORT:-5001}

echo "🛑 Menghentikan proses Aplikasi Absen (Port $PORT)..."

# 1. Hentikan via PID file jika ada
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$PID" ] && ps -p "$PID" > /dev/null 2>&1; then
        kill -15 "$PID" 2>/dev/null
        sleep 1
        kill -9 "$PID" 2>/dev/null
    fi
    rm -f "$PID_FILE"
fi

# 2. Hentikan via Port (lsof) jika masih ada yang tersisa
for p in $(lsof -ti :$PORT 2>/dev/null); do
    kill -9 "$p" 2>/dev/null || true
done

# 3. Fallback pkill pattern
pkill -9 -f "gunicorn.*5001" 2>/dev/null || true
pkill -9 -f "gunicorn.*wsgi:app" 2>/dev/null || true

# 4. Tunggu sampai port benar-benar lepas
for i in {1..10}; do
    if ! lsof -ti :$PORT > /dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

echo "✅ Semua proses aplikasi di port $PORT berhasil dihentikan."
