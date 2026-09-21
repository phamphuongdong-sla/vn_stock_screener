# -*- coding: utf-8 -*-
"""
Script kiểm tra kết nối Telegram nhanh
Chạy: python3 test_telegram.py
"""
import requests
import config

def test_connection():
    print("=" * 60)
    print("📲 KIỂM TRA KẾT NỐI TELEGRAM BOT")
    print("=" * 60)

    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID

    if not token or token == "YOUR_BOT_TOKEN_HERE":
        print("❌ LỖI: Bạn chưa điền TELEGRAM_BOT_TOKEN vào file config.py!")
        print("👉 Hãy xem hướng dẫn và điền Token vào config.py trước.")
        return

    if not chat_id or chat_id == "YOUR_CHAT_ID_HERE":
        print("❌ LỖI: Bạn chưa điền TELEGRAM_CHAT_ID vào file config.py!")
        print("👉 Hãy xem hướng dẫn và điền Chat ID vào config.py trước.")
        return

    print(f"[*] Đang thử gửi tin nhắn thử nghiệm tới Chat ID: {chat_id}...")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    test_msg = (
        "🐋👑 *KẾT NỐI TELEGRAM THÀNH CÔNG!* 👑🐋\n\n"
        "Chào bạn! Bot Quét Cổ Phiếu Cá Mập Việt Nam (AI Whale ProMax) đã được kết nối thành công với tài khoản Telegram của bạn.\n\n"
        "🚀 *Từ bây giờ, mỗi khi phát hiện mã có dòng tiền Cá Mập gom hàng, Bot sẽ tự động bắn tin nhắn về đây cho bạn!*"
    )

    payload = {
        "chat_id": chat_id,
        "text": test_msg,
        "parse_mode": "Markdown"
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        res_json = resp.json()
        if resp.status_code == 200 and res_json.get("ok"):
            print("✅ THÀNH CÔNG RỰC RỠ!")
            print("👉 Bạn hãy mở ứng dụng Telegram trên điện thoại/máy tính để kiểm tra tin nhắn vừa nhận được nhé!")
        else:
            print(f"❌ LỖI TỪ TELEGRAM: {res_json.get('description', 'Không xác định')}")
            print("👉 Vui lòng kiểm tra lại Token hoặc Chat ID.")
    except Exception as e:
        print(f"❌ LỖI KẾT NỐI: {e}")

if __name__ == "__main__":
    test_connection()
