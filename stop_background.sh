#!/bin/bash
# Script dừng Bot chạy ngầm

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

PID_FILE="$DIR/bot.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        kill "$PID"
        rm -f "$PID_FILE"
        echo "🛑 Đã dừng Bot thành công (PID: $PID)!"
        exit 0
    fi
fi

# Thử tìm tiến trình background_runner.py nếu không có file pid
PIDS=$(pgrep -f "background_runner.py")
if [ -n "$PIDS" ]; then
    kill $PIDS
    rm -f "$PID_FILE"
    echo "🛑 Đã dừng các tiến trình Bot đang chạy ngầm ($PIDS)!"
else
    echo "ℹ️ Hiện tại không có Bot nào đang chạy ngầm."
    rm -f "$PID_FILE"
fi
