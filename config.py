# -*- coding: utf-8 -*-
"""
File cấu hình cho Bot Quét Cổ Phiếu Cá Mập (Vietnam Stock Screener)
"""

import os
import json

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
# Đặt 0 = gửi ngay khi có tín hiệu mua (không lọc theo win rate)
MIN_ALERT_WINRATE = 0.0

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

# Số luồng phân tích chuyên sâu đồng thời
MAX_WORKERS = 16

# ==========================================
# 4. GDNL — Vùng Xu Hướng PRO (Pine Script Port)
# ==========================================
# Đồng bộ 100% với Pine Script GDNL - Vùng Xu Hướng PRO (Clean UI)

GDNL_ST_LENGTH   = 10     # Chu kỳ SuperTrend (EMA hlc3)
GDNL_ATR_LENGTH  = 14     # Chu kỳ ATR
GDNL_ATR_MULT    = 2.8    # Hệ số ATR SuperTrend
GDNL_EMA_FAST    = 20     # EMA nhanh
GDNL_EMA_SLOW    = 50     # EMA chậm
GDNL_ADX_LEN     = 14     # Chu kỳ ADX/DMI
GDNL_ADX_MIN     = 18.0   # ADX tối thiểu để xác nhận xu hướng
GDNL_VOL_LEN     = 20     # Chu kỳ Volume MA
GDNL_MIN_SCORE   = 4      # Điểm xu hướng tối thiểu để báo (1-6)
GDNL_PIVOT_LEN   = 15     # Chu kỳ Pivot High/Low
GDNL_TP1_RR      = 1.0    # R:R mức TP1
GDNL_TP2_RR      = 2.0    # R:R mức TP2

# ==========================================
# 5. DTPRO — Dòng Tiền & Xu Hướng PRO (Pine Script Port)
# ==========================================
# Đồng bộ 100% với "DÒNG TIỀN & XU HƯỚNG PRO - MASTER EDITION"

DTPRO_ST_LEN      = 10     # Chu kỳ Keltner SuperTrend
DTPRO_ATR_LEN     = 14     # Chu kỳ ATR
DTPRO_ST_MULT     = 2.8    # Hệ số nhân SuperTrend
DTPRO_EMA_FAST    = 20     # EMA nhanh (MTF scan)
DTPRO_EMA_SLOW    = 50     # EMA chậm (MTF scan)
DTPRO_NW_H        = 8.0    # Băng thông Nadaraya-Watson kernel
DTPRO_NW_MULT     = 3.0    # Hệ số nhân biên độ NW
DTPRO_NW_WIN      = 500    # Kích thước kernel NW (số nến)
DTPRO_LOOKBACK    = 7      # Cửa sổ chờ hợp lưu NW (Nến), mặc định 7 nến
DTPRO_RR1         = 1.0    # R:R mức TP1
DTPRO_RR2         = 2.0    # R:R mức TP2
DTPRO_HISTORY_DAYS = 1000  # Số ngày lịch sử (~677 phiên ~ 3 năm, tải siêu tốc <0.2s để thống kê đủ mẫu lệnh)

# ==========================================
# 6. THÔNG TIN DOANH NGHIỆP NIÊM YẾT
# ==========================================
_companies_cache = None

def get_company_info(symbol: str) -> dict:
    """Lấy thông tin công ty (tên đầy đủ, viết tắt) từ stock_companies.json."""
    global _companies_cache
    if _companies_cache is None:
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            json_path = os.path.join(base_dir, "stock_companies.json")
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    _companies_cache = json.load(f)
            else:
                _companies_cache = {}
        except Exception:
            _companies_cache = {}
    return _companies_cache.get(symbol.strip().upper(), {})



