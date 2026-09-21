#!/bin/bash
# Script chạy 1 chạm cho macOS (Double-click để chạy)

# Lấy đường dẫn thư mục chứa script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=================================================================="
echo "    🐋 KHỞI ĐỘNG BOT QUÉT CỔ PHIẾU CÁ MẬP (VIETNAM STOCK AI)      "
echo "=================================================================="
echo ""

# 1. Kiểm tra môi trường ảo Python
if [ ! -d "venv" ]; then
    echo "[*] Đang khởi tạo môi trường Python (venv)..."
    python3 -m venv venv
fi

source venv/bin/activate

# 2. Tự động kiểm tra và cài đặt thư viện nếu chưa có
echo "[*] Đang kiểm tra thư viện..."
if ! python3 -c "import requests, pandas, tabulate" &> /dev/null; then
    echo "[*] Đang tải & cài đặt thư viện tự động (requests, pandas, tabulate)..."
    pip install --upgrade pip
    pip install -r requirements.txt
fi

echo "[*] Thư viện đã sẵn sàng!"
echo ""

# 3. Chạy Bot
python3 main.py

# Giữ cửa sổ terminal không bị tắt đột ngột
echo ""
read -p "Nhấn phím [Enter] để đóng cửa sổ này..."
