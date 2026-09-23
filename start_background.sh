#!/bin/bash
# Script khởi động Bot chạy ngầm dưới nền macOS (Không cần mở Terminal)

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

PID_FILE="$DIR/bot.pid"
LOG_FILE="$DIR/bot.log"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "⚠️ Bot ĐANG CHẠY RỒI (PID: $PID)!"
        echo "👉 Xem log bằng lệnh: tail -f $LOG_FILE"
        exit 0
    fi
fi

# Chạy ngầm dưới nền với nohup (DÒNG TIỀN PRO)
nohup "$DIR/venv/bin/python3" "$DIR/dtpro_runner.py" --listen >> "$LOG_FILE" 2>&1 &
BOT_PID=$!
echo $BOT_PID > "$PID_FILE"

echo "=========================================================="
echo "🚀 ĐÃ KHỞI ĐỘNG BOT CHẠY NGẦM THÀNH CÔNG!"
echo "=========================================================="
echo "• Mã tiến trình (PID): $BOT_PID"
echo "• File nhật ký (Log) : $LOG_FILE"
echo "• Bạn có thể ĐÓNG CỬA SỔ NÀY thoải mái, Bot vẫn đang chạy ngầm!"
echo "• Để xem bot đang làm gì: tail -f $LOG_FILE"
echo "• Để dừng bot: ./stop_background.sh"
echo "=========================================================="
