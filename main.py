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

def display_and_notify_results(signals: list):
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
        print("\n[*] Đang gửi thông báo kết quả tới Telegram...")
        for s in signals:
            sent = send_telegram_alert(s)
            if sent:
                status = "🐋 CÁ MẬP" if s['is_whale'] else "Tiêu chuẩn"
                print(f" -> Đã gửi cảnh báo mã {s['symbol']} ({status}) tới Telegram.")
            time.sleep(0.5)

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
    print(" 2. Tự động chạy lặp liên tục trong phiên giao dịch (5 phút/lần)")
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
                            text = msg.get("text", "").strip().upper()
                            if text.startswith("/CHECK"):
                                parts = text.split()
                                if len(parts) > 1:
                                    text = parts[1]
                            if len(text) == 3 and text.isalpha():
                                print(f"\n📲 [LỆNH TELEGRAM] Người dùng yêu cầu soi mã: {text}")
                                import check
                                check.check_single_stock(text, send_telegram=True)
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
