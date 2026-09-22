# -*- coding: utf-8 -*-
"""
File cấu hình cho Bot Quét Cổ Phiếu Cá Mập (Vietnam Stock Screener)
"""

# ==========================================
# 1. CẤU HÌNH TELEGRAM CẢNH BÁO
# ==========================================
# Hướng dẫn tạo bot:
# 1. Chat với @BotFather trên Telegram -> gõ /newbot -> lấy TOKEN (dạng 123456789:ABCdef...)
# 2. Chat với @userinfobot -> lấy Chat ID của bạn (dạng số: 987654321)
TELEGRAM_ENABLED = True
TELEGRAM_BOT_TOKEN = "8969001909:AAF8o9IWI3YcLbNmKvH4IqiYrGlbpXZPrXw"
TELEGRAM_CHAT_ID = "2125548447"

# ==========================================
# 2. TIÊU CHUẨN KHẮT KHE: CHẮC CHẮN CÓ CÁ MẬP (SMART MONEY)
# ==========================================
# Chỉ hiển thị và cảnh báo những mã CHẮC CHẮN CÓ CÁ MẬP (Nếu bật True, chỉ báo các mã có Logo Cá Mập)
STRICT_WHALE_ONLY = False

# Ngưỡng độ tin cậy tối thiểu để bắn cảnh báo về Telegram (%)
MIN_ALERT_WINRATE = 75.0

# Giá trị giao dịch tối thiểu trong ngày (VNĐ) - Loại bỏ cổ phiếu rác, penny không thanh khoản
MIN_TRADE_VALUE = 3_000_000_000   # 3 tỷ VNĐ trở lên

# Khối lượng Cá Mập bùng nổ so với trung bình 20 phiên (SMA 20)
# 1.5 = Khối lượng hiện tại vượt 150% so với trung bình 20 ngày (Nhỏ lẻ không thể tự tạo ra được)
WHALE_VOLUME_RATIO = 1.5

# Tỷ lệ râu nến dưới rút chân tối thiểu để xác nhận Cá mập vét hàng quét thanh khoản (Spring)
# 0.40 = Râu nến dưới chiếm ít nhất 40% toàn bộ biên độ nến
WHALE_LOWER_WICK_RATIO = 0.40

# Tỷ lệ lợi nhuận / rủi ro (Risk : Reward)
RR_TP1 = 1.0   # Chốt 1 phần & dời SL về hòa vốn
RR_TP2 = 2.0   # Chốt lời mục tiêu
RR_TP3 = 3.0   # Chốt lời tối đa theo sóng

# ==========================================
# 3. CẤU HÌNH LỊCH QUÉT TỰ ĐỘNG
# ==========================================
# Khoảng thời gian nghỉ giữa mỗi lần quét (giây) khi chạy chế độ lặp
SCAN_INTERVAL_SECONDS = 60   # 1 phút quét 1 lần theo thời gian thực trong giờ giao dịch

# Các sàn muốn quét: "HOSE", "HNX"
EXCHANGES = ["HOSE", "HNX"]
