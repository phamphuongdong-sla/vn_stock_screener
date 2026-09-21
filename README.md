# 🐋 AI WHALE & SMART MONEY SCREENER — THỊ TRƯỜNG CHỨNG KHOÁN VIỆT NAM

Hệ thống tự động quét toàn bộ hơn **1.600 mã cổ phiếu trên 3 sàn (HOSE, HNX, UPCoM)** để phát hiện ngay lập tức các mã có dấu chân của **Cá Mập (Smart Money)**:
- **Khối lượng bùng nổ (Volume Surge):** Lớn hơn 1.3x - 1.5x so với trung bình 20 phiên.
- **Hành vi rũ bỏ (Liquidity Sweep / Spring):** Nến rút chân quét thanh khoản hoặc nến vượt đỉnh (SOS Breakout).
- **Tính toán tự động:** Giá vào (Entry), Cắt lỗ (SL), Chốt lời TP1 (1R), TP2 (2R), TP3 (3R).
- **Cảnh báo Real-time:** Hiển thị dạng bảng đẹp trên màn hình và gửi thẳng thông báo về **Telegram**.

---

## 🛠️ CÁCH CÀI ĐẶT & CHẠY (TRÊN MAC / LINUX / WINDOWS)

### Bước 1: Mở Terminal và di chuyển vào thư mục dự án
```bash
cd /Users/mrdong/.gemini/antigravity/scratch/vn_stock_screener
```

### Bước 2: Tạo môi trường ảo Python & Cài đặt thư viện
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 📲 CÁCH CẤU HÌNH GỬI THÔNG BÁO VỀ TELEGRAM (TÙY CHỌN)

Nếu muốn nhận tin nhắn trực tiếp về điện thoại khi có mã nổ tín hiệu:

1. **Lấy Bot Token:**
   - Mở Telegram, tìm bot `@BotFather`.
   - Gõ lệnh `/newbot` và đặt tên cho bot.
   - Nhận chuỗi `TOKEN` (Ví dụ: `7123456789:AAFn_XXXXXXX...`).

2. **Lấy Chat ID:**
   - Tìm bot `@userinfobot` trên Telegram và bấm `Start`.
   - Bot sẽ gửi lại `Id` của bạn (Ví dụ: `123456789`).

3. **Điền vào file `config.py`:**
   Mở file `config.py` và sửa:
   ```python
   TELEGRAM_ENABLED = True
   TELEGRAM_BOT_TOKEN = "ĐIỀN_TOKEN_VÀO_ĐÂY"
   TELEGRAM_CHAT_ID = "ĐIỀN_CHAT_ID_VÀO_ĐÂY"
   ```

---

## 🚀 CHẠY CHƯƠNG TRÌNH

Sau khi cài đặt xong, gõ lệnh:
```bash
python3 main.py
```

* **Chế độ 1 (Quét ngay):** Nhấn số `1` để quét toàn bộ sàn ngay lập tức và in bảng kết quả.
* **Chế độ 2 (Tự động canh phiên):** Nhấn số `2` để Bot tự động chạy ngầm, cứ mỗi 5 phút trong phiên giao dịch sẽ quét 1 lần và tự động gửi tin nhắn Telegram cho bạn.
