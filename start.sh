#!/bin/bash
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

PID_FILE="$PROJECT_DIR/gunicorn.pid"
LOG_FILE="$PROJECT_DIR/gunicorn.log"
PORT=${PORT:-5001}

# Periksa apakah proses sudah berjalan
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$PID" ] && ps -p "$PID" > /dev/null 2>&1; then
        echo "⚠️  Aplikasi Absen sudah berjalan dengan PID $PID pada port $PORT."
        exit 0
    else
        rm -f "$PID_FILE"
    fi
fi

# Cari path Python / Gunicorn di virtual environment
PYTHON_BIN=""
GUNICORN_BIN=""

if [ -f "$PROJECT_DIR/venv/bin/python" ]; then
    PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
    GUNICORN_BIN="$PROJECT_DIR/venv/bin/gunicorn"
elif [ -f "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
    GUNICORN_BIN="$PROJECT_DIR/.venv/bin/gunicorn"
else
    PYTHON_BIN="python3"
    GUNICORN_BIN="gunicorn"
fi

# Jika gunicorn belum terinstall di venv, otomatis install
if [ ! -f "$GUNICORN_BIN" ] && ! command -v "$GUNICORN_BIN" > /dev/null 2>&1; then
    echo "⚙️  Gunicorn belum terpasang. Memasang gunicorn sekarang..."
    "$PYTHON_BIN" -m pip install gunicorn
fi

echo "🚀 Menjalankan Aplikasi Absen Seminar di background (Port $PORT)..."

if [ -f "$GUNICORN_BIN" ]; then
    nohup "$GUNICORN_BIN" --no-control-socket --workers 3 --bind 0.0.0.0:$PORT --pid "$PID_FILE" wsgi:app >> "$LOG_FILE" 2>&1 &
elif command -v gunicorn > /dev/null 2>&1; then
    nohup gunicorn --no-control-socket --workers 3 --bind 0.0.0.0:$PORT --pid "$PID_FILE" wsgi:app >> "$LOG_FILE" 2>&1 &
else
    # Fallback menjalankan app.py jika gunicorn tidak tersedia
    echo "⚠️  Menjalankan fallback dengan Python..."
    nohup "$PYTHON_BIN" app.py >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
fi

for i in 1 2 3; do
    if [ -f "$PID_FILE" ] && [ -s "$PID_FILE" ]; then
        NEW_PID=$(cat "$PID_FILE" 2>/dev/null)
        echo "✅ Berhasil dijalankan! (PID: $NEW_PID)"
        echo "📄 File log: $LOG_FILE"
        exit 0
    fi
    sleep 1
done

echo "❌ Gagal menjalankan atau PID belum terbentuk. Silakan cek $LOG_FILE"
