# -*- coding: utf-8 -*-
"""
Chương trình chạy ngầm 24/7 cho Bot Cá Mập (Background Daemon)
- Tự động quét thị trường trong giờ giao dịch
- Luôn lắng nghe tin nhắn từ Telegram (bạn nhắn mã nào là trả lời mã đó)
- Chạy hoàn toàn dưới nền, không cần mở cửa sổ Terminal
"""

import time
import requests
from datetime import datetime
import config
import screener
import main
import check

import telegram_bot

def log(msg: str):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now_str}] {msg}"
    print(line, flush=True)

def run_daemon():
    log("🚀 KHỞI ĐỘNG BOT CÁ MẬP CHẠY NGẦM (DAEMON)...")
    log(f"[*] Cấu hình Telegram: {'BẬT (Chat ID: ' + config.TELEGRAM_CHAT_ID + ')' if config.TELEGRAM_ENABLED else 'TẮT'}")
    
    last_scan_time = 0
    last_update_id = 0

    log("[*] Bot đã sẵn sàng chạy ngầm 24/7. Đang lắng nghe lệnh...")

    while True:
        # 1. Lắng nghe tin nhắn từ Telegram (Hỗ trợ nhiều người dùng tra cứu & hướng dẫn)
        if config.TELEGRAM_ENABLED:
            try:
                u_url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=1"
                r = requests.get(u_url, timeout=3)
                if r.status_code == 200:
                    for up in r.json().get("result", []):
                        last_update_id = up.get("update_id", last_update_id)
                        msg = up.get("message", {})
                        chat_id = msg.get("chat", {}).get("id")
                        raw_text = msg.get("text", "").strip()
                        if not raw_text or not chat_id:
                            continue
                        
                        text = raw_text.upper()
                        # Kiểm tra lệnh trợ giúp: /start, /help, /huongdan (có hoặc không có dấu /)
                        if text in ["/START", "/HELP", "/HUONGDAN", "START", "HELP", "HUONG DAN"] or text.startswith("/START") or text.startswith("/HELP") or text.startswith("/HUONGDAN"):
                            log(f"📖 Gửi hướng dẫn sử dụng tới Chat ID {chat_id}")
                            telegram_bot.send_welcome_help(str(chat_id))
                            continue

                        # Kiểm tra lệnh soi mã: /soi, /check hoặc gõ thẳng 3 chữ cái
                        target_symbol = None
                        if text.startswith("/CHECK") or text.startswith("/SOI"):
                            parts = text.split()
                            if len(parts) > 1:
                                target_symbol = parts[1]
                        elif len(text) == 3 and text.isalpha():
                            target_symbol = text

                        if target_symbol and len(target_symbol) == 3 and target_symbol.isalpha():
                            log(f"📲 Nhận lệnh từ Chat ID {chat_id} yêu cầu soi mã: {target_symbol}")
                            check.check_single_stock(target_symbol, send_telegram=True, target_chat_id=str(chat_id))
            except Exception:
                pass

        # 2. Quét định kỳ toàn sàn trong giờ giao dịch
        current_now = time.time()
        if current_now - last_scan_time >= config.SCAN_INTERVAL_SECONDS:
            if main.is_trading_hour():
                log("⏰ Trong giờ giao dịch -> Bắt đầu quét toàn bộ thị trường...")
                try:
                    signals = screener.run_screener()
                    main.display_and_notify_results(signals)
                except Exception as e:
                    log(f"[Lỗi quét] {e}")
            else:
                log("💤 Ngoài giờ giao dịch. Bot vẫn đang trực và chờ tin nhắn Telegram của bạn...")
            last_scan_time = current_now

        time.sleep(2)

if __name__ == "__main__":
    run_daemon()
