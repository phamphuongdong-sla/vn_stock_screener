# -*- coding: utf-8 -*-
"""
File chạy chính của Bot Quét Cổ Phiếu Cá Mập ProMax (Vietnam Stock Screener)
Chạy: python3 main.py hoặc double-click run.command
"""

import sys
import time
from datetime import datetime
from tabulate import tabulate

import config
from screener import run_screener
from telegram_bot import send_telegram_alert

def is_trading_hour() -> bool:
    """
    Kiểm tra xem hiện tại có phải trong phiên giao dịch chứng khoán Việt Nam hay không
    (Thứ 2 đến Thứ 6, từ 9h00 - 11h30 và 13h00 - 15h00)
    """
    now = datetime.now()
    if now.weekday() > 4:
        return False
    
    current_time = now.time()
    t_0900 = datetime.strptime("09:00", "%H:%M").time()
    t_1130 = datetime.strptime("11:30", "%H:%M").time()
    t_1300 = datetime.strptime("13:00", "%H:%M").time()
    t_1500 = datetime.strptime("15:00", "%H:%M").time()

    return (t_0900 <= current_time <= t_1130) or (t_1300 <= current_time <= t_1500)

def load_alerted_stocks_today() -> set:
    """
    Tải danh sách các mã đã bắn cảnh báo hôm nay.
    Hỗ trợ đồng bộ đa môi trường (GitHub Actions không ổ cứng lưu trạng thái qua tin nhắn ghim Telegram).
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    alerted = set()

    # 1. Thử đọc từ file json cục bộ
    try:
        import os, json
        if os.path.exists("alerted_stocks.json"):
            with open("alerted_stocks.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("date") == today_str:
                    alerted.update(data.get("stocks", []))
    except Exception:
        pass

    # 2. Đồng bộ từ tin nhắn trạng thái trên Telegram (Bảo đảm GitHub Actions không bị gửi lặp)
    if config.TELEGRAM_ENABLED:
        try:
            import requests
            r = requests.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getChat?chat_id={config.TELEGRAM_CHAT_ID}", timeout=5)
            pinned = r.json().get("result", {}).get("pinned_message", {})
            text = pinned.get("text", "")
            if "#BOT_STATE" in text and today_str in text:
                parts = text.split("STOCKS:")
                if len(parts) > 1:
                    stocks = [s.strip() for s in parts[1].split(",") if s.strip()]
                    alerted.update(stocks)
        except Exception:
            pass

    return alerted

def save_alerted_stocks_today(alerted: set):
    """
    Lưu danh sách mã đã cảnh báo hôm nay vào file cục bộ và cập nhật tin nhắn trạng thái trên Telegram.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    stock_list = sorted(list(alerted))

    # 1. Lưu file json cục bộ
    try:
        import json
        with open("alerted_stocks.json", "w", encoding="utf-8") as f:
            json.dump({"date": today_str, "stocks": stock_list}, f, ensure_ascii=False)
    except Exception:
        pass

    # 2. Cập nhật tin nhắn ghim trên Telegram để GitHub Actions các lần chạy tiếp theo đọc được
    if config.TELEGRAM_ENABLED:
        try:
            import requests
            state_text = (
                f"🤖 [TRẠNG THÁI BOT] #BOT_STATE {today_str}\n"
                f"⏰ Cập nhật: {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}\n"
                f"📊 Đã kích hoạt điểm mua hôm nay ({len(stock_list)} mã):\n"
                f"STOCKS:{', '.join(stock_list)}"
            )
            r = requests.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getChat?chat_id={config.TELEGRAM_CHAT_ID}", timeout=5)
            pinned = r.json().get("result", {}).get("pinned_message", {})
            msg_id = pinned.get("message_id")

            if msg_id:
                requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/editMessageText", json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "message_id": msg_id,
                    "text": state_text
                }, timeout=5)
            else:
                r_send = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage", json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": state_text,
                    "disable_notification": True
                }, timeout=5)
                new_id = r_send.json().get("result", {}).get("message_id")
                if new_id:
                    requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/pinChatMessage", json={
                        "chat_id": config.TELEGRAM_CHAT_ID,
                        "message_id": new_id,
                        "disable_notification": True
                    }, timeout=5)
        except Exception:
            pass

def display_and_notify_results(signals: list):
    alerted_stocks_today = load_alerted_stocks_today()

    if not signals:
        print("ℹ️ Hiện tại không tìm thấy mã nào thỏa mãn điều kiện Cá Mập.")
        return

    table_data = []
    for s in signals:
        table_data.append([
            f"{s['whale_badge']} [{s.get('win_rate', 80):.0f}%]",
            s['symbol'],
            s['exchange'],
            s['price_vnd'],
            f"{s['change_pct']:+.2f}%",
            f"{s['vol_ratio']:.1f}x",
            f"{s['trade_value_bil']:.1f} Tỷ",
            s['pattern'],
            f"{s['sl_vnd']} ({s.get('sl_pct', 0):+.1f}%)",
            f"{s['tp1_vnd']} ({s.get('tp1_pct', 0):+.1f}%)",
            f"{s['tp2_vnd']} ({s.get('tp2_pct', 0):+.1f}%)",
            f"{s['tp3_vnd']} ({s.get('tp3_pct', 0):+.1f}%)"
        ])

    headers = [
        "Xác Nhận", "Mã", "Sàn", "Giá Hiện Tại", "Tăng/Giảm",
        "Vol/MA20", "Giá Trị GD", "Hành Động Giá", "Cắt Lỗ (SL)",
        "TP1 (1R)", "TP2 (2R)", "TP3 (3R)"
    ]
    print("\n" + tabulate(table_data, headers=headers, tablefmt="fancy_grid"))

    # Gửi thông báo Telegram nếu được kích hoạt
    if config.TELEGRAM_ENABLED:
        print(f"\n[*] Đang lọc và gửi các tín hiệu mới đạt từ {config.MIN_ALERT_WINRATE:.0f}% trở lên tới Telegram...")
        print(f"[*] Danh sách mã đã gửi hôm nay: {sorted(list(alerted_stocks_today)) if alerted_stocks_today else 'Chưa có'}")
        alerted_count = 0
        for s in signals:
            sym = s.get('symbol')
            if sym in alerted_stocks_today:
                continue
            if s.get('win_rate', 0) >= config.MIN_ALERT_WINRATE:
                sent = send_telegram_alert(s)
                if sent:
                    alerted_stocks_today.add(sym)
                    alerted_count += 1
                    status = "🐋 CÁ MẬP" if s['is_whale'] else "Tiêu chuẩn"
                    print(f" -> [ĐẠT {s.get('win_rate', 0):.0f}%] Đã gửi cảnh báo mã {s['symbol']} ({status}) tới Telegram.")
                time.sleep(0.5)

        if alerted_count > 0:
            save_alerted_stocks_today(alerted_stocks_today)
            print(f"✅ Đã cập nhật trạng thái: Tổng cộng {len(alerted_stocks_today)} mã đã kích hoạt hôm nay.")
        else:
            print(f" -> Không có tín hiệu MỚI nào cần gửi (đã gửi trước đó hoặc chưa đạt ngưỡng {config.MIN_ALERT_WINRATE:.0f}%).")

def main():
    print(r"""
  __      ___      _                      _____ _             _    
  \ \    / / |    | |                    / ____| |           | |   
   \ \  / /| |__  | |__   __ _ _ __ ___  | (___ | |__   __ _ | | __
    \ \/ / | '_ \ / _` | / _` | '__/ _ \  \___ \| '_ \ / _` || |/ /
     \  /  | | | | (_| || (_| | | |  __/  ____) | | | | (_| ||   < 
      \/   |_| |_|\__,_| \__,_|_|  \___| |_____/|_| |_|\__,_||_|\_\
      🐋 AI CÁ MẬP PROMAX — ĐỒNG BỘ 100% PINE SCRIPT (VNĐ) 🐋
    """)

    print(f"[*] Cấu hình Telegram: {'BẬT' if config.TELEGRAM_ENABLED else 'TẮT (Xem config.py nếu muốn bật)'}")
    print(f"[*] Hợp lưu bộ lọc: SuperTrend + Mây Ichimoku + Volume Cá Mập >={config.WHALE_VOLUME_RATIO}x")
    print(f"[*] Ngưỡng rút chân quét thanh khoản: >={int(config.WHALE_LOWER_WICK_RATIO*100)}% biên độ nến")
    print(f"[*] Giá trị giao dịch tối thiểu: >={config.MIN_TRADE_VALUE / 1_000_000_000:.1f} Tỷ VNĐ")
    print("-" * 75)
    print("Chọn chế độ chạy:")
    print(" 1. Quét toàn bộ sàn ngay lập tức (In bảng kết quả định dạng VNĐ)")
    print(f" 2. Tự động chạy lặp liên tục trong phiên giao dịch ({config.SCAN_INTERVAL_SECONDS}s/lần — thời gian thực)")
    print(" 3. Soi chi tiết 1 mã bất kỳ (Nhập mã: HPG, SSI, VCB, FPT...)")
    
    choice = input("\nNhập lựa chọn (1, 2 hoặc 3) [Mặc định: 1]: ").strip()
    if choice == "3":
        import check
        ticker = input("Nhập mã cổ phiếu bạn muốn soi (VD: HPG, SSI, FPT...): ").strip()
        if ticker:
            check.check_single_stock(ticker)
    elif choice == "2":
        print(f"\n[*] Bot bắt đầu chế độ tự động giám sát phiên giao dịch (Chu kỳ {config.SCAN_INTERVAL_SECONDS} giây)...")
        print("[*] 💡 MẸO: Bạn có thể mở Telegram chat trực tiếp tên mã (VD: HPG, SSI, VCB...) để Bot soi và trả lời ngay!")
        print("[*] Nhấn Ctrl+C để dừng chương trình.\n")
        
        last_scan_time = 0
        last_update_id = 0
        
        # Lấy update_id mới nhất để không đọc lại tin nhắn cũ
        if config.TELEGRAM_ENABLED:
            try:
                import requests
                r = requests.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates", timeout=5)
                updates = r.json().get("result", [])
                if updates:
                    last_update_id = updates[-1]["update_id"]
            except Exception:
                pass

        while True:
            # 1. Kiểm tra xem người dùng có gửi mã từ Telegram không
            if config.TELEGRAM_ENABLED:
                try:
                    import requests
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
                            if text.startswith("/START") or text.startswith("/HELP") or text.startswith("/HUONGDAN"):
                                print(f"\n📖 [LỆNH TELEGRAM] Gửi hướng dẫn tới Chat ID: {chat_id}")
                                import telegram_bot
                                telegram_bot.send_welcome_help(str(chat_id))
                                continue

                            target_symbol = None
                            if text.startswith("/CHECK") or text.startswith("/SOI"):
                                parts = text.split()
                                if len(parts) > 1:
                                    target_symbol = parts[1]
                            elif len(text) == 3 and text.isalpha():
                                target_symbol = text

                            if target_symbol and len(target_symbol) == 3 and target_symbol.isalpha():
                                print(f"\n📲 [LỆNH TELEGRAM] Nhận yêu cầu soi mã: {target_symbol} từ Chat ID {chat_id}")
                                import check
                                check.check_single_stock(target_symbol, send_telegram=True, target_chat_id=str(chat_id))
                except Exception:
                    pass

            # 2. Quét định kỳ toàn sàn trong giờ giao dịch
            current_now = time.time()
            if current_now - last_scan_time >= config.SCAN_INTERVAL_SECONDS:
                now_str = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
                if is_trading_hour():
                    print(f"\n[{now_str}] Đang trong phiên giao dịch -> Bắt đầu quét thị trường...")
                    signals = run_screener()
                    display_and_notify_results(signals)
                else:
                    print(f"[{now_str}] Ngoài phiên giao dịch. Đang lắng nghe lệnh soi mã từ Telegram của bạn...")
                last_scan_time = current_now

            time.sleep(2)

if __name__ == "__main__":
    main()
