# -*- coding: utf-8 -*-
"""
Bot Cá Mập - Chạy ngầm 24/7 với 2 luồng song song:
  Thread 1 (Telegram Listener): Lắng nghe tin nhắn người dùng liên tục, phản hồi ngay.
  Thread 2 (Market Scanner):    Quét toàn sàn mỗi 1 phút trong giờ giao dịch, bắn cảnh báo Telegram.

Cơ chế chống spam: Mỗi mã chỉ bắn cảnh báo 1 lần/ngày (lưu file + Telegram pinned message).
"""

import time
import threading
import requests
from datetime import datetime

import config
import screener
import main
import check
import telegram_bot


# ─── LOGGER ───────────────────────────────────────────────────────────────────
def log(msg: str):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] {msg}", flush=True)


# ─── TELEGRAM LISTENER THREAD ─────────────────────────────────────────────────
def telegram_listener_thread():
    """
    Luồng lắng nghe Telegram liên tục (vòng lặp 2 giây).
    Xử lý: tra cứu mã (VD: MSN, HPG), /start, /help, /soi, /check.
    """
    last_update_id = 0

    # Bỏ qua tin nhắn cũ từ trước khi khởi động
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates",
            timeout=5
        )
        updates = r.json().get("result", [])
        if updates:
            last_update_id = updates[-1]["update_id"]
            log(f"[Telegram] Bỏ qua {len(updates)} tin nhắn cũ. Sẵn sàng lắng nghe mới.")
    except Exception:
        pass

    log("[Telegram] 🎧 Luồng lắng nghe Telegram đã khởi động. Sẵn sàng nhận lệnh...")

    while True:
        try:
            u_url = (
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
                f"/getUpdates?offset={last_update_id + 1}&timeout=2"
            )
            r = requests.get(u_url, timeout=6)
            if r.status_code != 200:
                time.sleep(3)
                continue

            for up in r.json().get("result", []):
                last_update_id = up.get("update_id", last_update_id)
                msg = up.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                raw_text = msg.get("text", "").strip()

                if not raw_text or not chat_id:
                    continue

                text = raw_text.upper()
                parts = text.split()
                cmd = parts[0].split("@")[0] if parts else ""

                # Lệnh trợ giúp
                if cmd in ["/START", "/HELP", "/HUONGDAN", "START", "HELP"]:
                    log(f"[Telegram] 📖 Gửi hướng dẫn tới Chat ID {chat_id}")
                    threading.Thread(
                        target=telegram_bot.send_welcome_help,
                        args=(str(chat_id),),
                        daemon=True
                    ).start()
                    continue

                # Lệnh soi mã: /soi VCB, /check VCB hoặc gõ thẳng: VCB
                target_symbol = None
                if cmd in ["/CHECK", "/SOI"] and len(parts) > 1:
                    target_symbol = parts[1]
                elif len(text) <= 5 and text.isalpha():
                    target_symbol = text

                if target_symbol and 2 <= len(target_symbol) <= 5 and target_symbol.isalpha():
                    log(f"[Telegram] 📲 Chat ID {chat_id} yêu cầu soi mã: {target_symbol}")
                    # Chạy trên thread riêng để không block listener
                    threading.Thread(
                        target=_handle_stock_query,
                        args=(target_symbol, str(chat_id)),
                        daemon=True
                    ).start()

        except requests.exceptions.Timeout:
            pass  # Timeout là bình thường với long-polling
        except Exception as e:
            log(f"[Telegram] ⚠️ Lỗi kết nối: {e}")
            time.sleep(5)


def _handle_stock_query(symbol: str, chat_id: str):
    """Xử lý yêu cầu soi mã từ người dùng Telegram (chạy trên thread riêng)."""
    try:
        check.check_single_stock(symbol, send_telegram=True, target_chat_id=chat_id)
    except Exception as e:
        log(f"[Telegram] ❌ Lỗi khi soi mã {symbol}: {e}")
        try:
            requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": f"❌ Không thể phân tích mã *{symbol}* lúc này. Vui lòng thử lại sau.",
                    "parse_mode": "Markdown"
                },
                timeout=5
            )
        except Exception:
            pass


# ─── MARKET SCANNER THREAD ────────────────────────────────────────────────────
def market_scanner_thread():
    """
    Luồng quét toàn sàn định kỳ theo config.SCAN_INTERVAL_SECONDS (mặc định 60 giây).
    Chỉ quét trong giờ giao dịch. Cảnh báo Telegram chống spam: 1 lần/mã/ngày.
    """
    last_scan_time = 0

    log(f"[Scanner] 🔍 Luồng quét thị trường đã khởi động (Chu kỳ: {config.SCAN_INTERVAL_SECONDS}s).")

    while True:
        current_now = time.time()

        if current_now - last_scan_time >= config.SCAN_INTERVAL_SECONDS:
            last_scan_time = current_now

            if main.is_trading_hour():
                now_str = datetime.now().strftime("%H:%M:%S")
                log(f"[Scanner] ⏰ [{now_str}] Đang trong giờ giao dịch → Quét toàn bộ thị trường...")
                try:
                    signals = screener.run_screener()
                    if signals:
                        log(f"[Scanner] ✅ Tìm thấy {len(signals)} tín hiệu. Đang lọc và cảnh báo Telegram...")
                    main.display_and_notify_results(signals)
                except Exception as e:
                    log(f"[Scanner] ❌ Lỗi quét thị trường: {e}")
            else:
                now_str = datetime.now().strftime("%H:%M")
                log(f"[Scanner] 💤 [{now_str}] Ngoài giờ giao dịch. Đang chờ... (Bot Telegram vẫn hoạt động)")

        time.sleep(5)


# ─── MAIN ENTRY ───────────────────────────────────────────────────────────────
def run_daemon():
    log("=" * 60)
    log("🚀 KHỞI ĐỘNG BOT CÁ MẬP PROMAX — CHẾ ĐỘ THỜI GIAN THỰC")
    log("=" * 60)
    log(f"  📡 Telegram : {'BẬT (Chat ID: ' + config.TELEGRAM_CHAT_ID + ')' if config.TELEGRAM_ENABLED else 'TẮT'}")
    log(f"  ⏱  Chu kỳ quét: {config.SCAN_INTERVAL_SECONDS} giây / lần")
    log(f"  📊 Ngưỡng cảnh báo: >= {config.MIN_ALERT_WINRATE:.0f}% độ tin cậy")
    log(f"  💰 Thanh khoản tối thiểu: >= {config.MIN_TRADE_VALUE / 1_000_000_000:.0f} Tỷ VNĐ")
    log("=" * 60)

    # Khởi động 2 thread song song
    t_telegram = threading.Thread(target=telegram_listener_thread, daemon=True, name="TelegramListener")
    t_scanner  = threading.Thread(target=market_scanner_thread,   daemon=True, name="MarketScanner")

    t_telegram.start()
    t_scanner.start()

    log("[Main] ✅ Cả 2 luồng đã khởi động thành công. Bot đang chạy ngầm 24/7.")
    log("[Main] 💡 Mẹo: Nhắn thẳng mã cổ phiếu vào Telegram (VD: MSN, HPG, VCB) để soi ngay!")
    log("[Main] 🛑 Để dừng bot: ./stop_background.sh")

    # Giữ main thread sống, watchdog kiểm tra thread không bị chết
    while True:
        time.sleep(30)
        if not t_telegram.is_alive():
            log("[Watchdog] ⚠️ Luồng Telegram bị chết! Đang khởi động lại...")
            t_telegram = threading.Thread(target=telegram_listener_thread, daemon=True, name="TelegramListener")
            t_telegram.start()
        if not t_scanner.is_alive():
            log("[Watchdog] ⚠️ Luồng Scanner bị chết! Đang khởi động lại...")
            t_scanner = threading.Thread(target=market_scanner_thread, daemon=True, name="MarketScanner")
            t_scanner.start()


if __name__ == "__main__":
    run_daemon()
