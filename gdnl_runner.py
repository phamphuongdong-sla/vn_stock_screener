# -*- coding: utf-8 -*-
"""
gdnl_runner.py — Entry point cho GitHub Actions và cũng dùng local.

Modes:
  python gdnl_runner.py               → Quét + xử lý tin nhắn (GitHub Actions)
  python gdnl_runner.py --check HPG   → Test phân tích 1 mã rồi in ra màn hình
  python gdnl_runner.py --scan        → Quét nhanh toàn sàn, in kết quả
  python gdnl_runner.py --listen      → Chạy daemon polling Telegram 24/7 (local)

Luồng GitHub Actions (mặc định):
  1. Lấy tất cả tin nhắn chưa xử lý từ Telegram → phân tích & phản hồi ngay
  2. Kiểm tra có đang trong giờ giao dịch không
  3. Nếu có → quét toàn sàn, gửi tín hiệu về channel mặc định
  4. Ack toàn bộ updates đã xử lý
"""

import sys
import time
import os
from datetime import datetime

import config
from screener import is_trading_hour
import gdnl_bot
import gdnl_screener


def run_github_actions_mode():
    """
    Mode mặc định: chạy 1 lần, xử lý tin nhắn + quét sàn.
    Phù hợp với GitHub Actions trigger mỗi 5 phút.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 GDNL Bot khởi động (GitHub Actions mode)")

    # ── Bước 1: Đọc & xử lý tất cả tin nhắn đang pending
    print("[1/3] Đọc tin nhắn Telegram đang chờ...")
    updates = gdnl_bot.get_pending_updates(offset=0)
    if updates:
        print(f"  → Có {len(updates)} tin nhắn cần xử lý.")
        last_id = gdnl_bot.process_updates(
            updates,
            run_scan_fn=lambda: gdnl_screener.run_gdnl_screener(signal_only=True)
        )
        # Ack để không xử lý lại lần sau
        if last_id > 0:
            gdnl_bot.ack_update(last_id)
            print(f"  → Đã ack đến update_id={last_id}")
    else:
        print("  → Không có tin nhắn mới.")

    # ── Bước 2: Quét toàn sàn nếu trong giờ giao dịch
    print("[2/3] Kiểm tra giờ giao dịch...")
    if is_trading_hour():
        print("  → Đang trong giờ giao dịch. Bắt đầu quét toàn sàn...")
        try:
            signals = gdnl_screener.run_gdnl_screener(signal_only=True)
            now_str = datetime.now().strftime("%H:%M %d/%m")
            summary = gdnl_bot.format_scan_summary(signals, f"[{now_str}]")

            if signals:
                gdnl_bot.send_alert_to_default(summary)
                print(f"  → Đã gửi {len(signals)} tín hiệu về Telegram.")
            else:
                print("  → Không có tín hiệu mới trong phiên này.")
        except Exception as e:
            print(f"  → [Lỗi quét] {e}")
    else:
        print("  → Ngoài giờ giao dịch. Bỏ qua quét.")

    print("[3/3] Hoàn tất. Bot sẽ được kích hoạt lại theo lịch tiếp theo.")


def run_daemon_mode():
    """
    Mode polling 24/7 (chạy local / VPS).
    Lắng nghe tin nhắn liên tục + quét định kỳ trong giờ giao dịch.
    """
    print("🚀 GDNL Bot khởi động (Daemon mode 24/7)...")
    last_update_id = 0
    last_scan_time = 0

    while True:
        # Lắng nghe tin nhắn
        try:
            updates = gdnl_bot.get_pending_updates(offset=last_update_id + 1)
            if updates:
                last_id = gdnl_bot.process_updates(
                    updates,
                    run_scan_fn=lambda: gdnl_screener.run_gdnl_screener(signal_only=True)
                )
                last_update_id = max(last_update_id, last_id)
        except Exception as e:
            print(f"[Lỗi polling] {e}")

        # Quét định kỳ trong giờ giao dịch
        now = time.time()
        if now - last_scan_time >= config.SCAN_INTERVAL_SECONDS:
            if is_trading_hour():
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Quét toàn sàn...")
                try:
                    signals = gdnl_screener.run_gdnl_screener(signal_only=True)
                    if signals:
                        now_str = datetime.now().strftime("%H:%M %d/%m")
                        summary = gdnl_bot.format_scan_summary(signals, f"[{now_str}]")
                        gdnl_bot.send_alert_to_default(summary)
                except Exception as e:
                    print(f"[Lỗi quét] {e}")
            last_scan_time = now

        time.sleep(2)


def run_check_mode(symbol: str):
    """Test phân tích 1 mã, in kết quả ra màn hình và gửi Telegram."""
    print(f"\n🔍 Phân tích chi tiết mã: {symbol.upper()}")
    res = gdnl_screener.analyze_single_symbol(symbol)
    if res is None:
        print(f"❌ Không tìm thấy dữ liệu cho mã '{symbol}'")
        return

    # In console
    print(f"\n{'='*60}")
    print(f"  {res['symbol']} ({res['exchange']}) — {res['updated_time']}")
    print(f"  Giá: {res['price_vnd']} ({res['change_pct']:+.2f}%)")
    print(f"  Xu hướng: {res['trend_label']} | {res['cloud_label']}")
    print(f"  ADX: {res['adx']} | DI+: {res['di_plus']} | DI-: {res['di_minus']}")
    print(f"  Volume: {res['vol_ratio']:.1f}x MA20")
    print(f"  MTF — H1: {res['mtf_h1_str']} | M30: {res['mtf_m30_str']} | M5: {res['mtf_m5_str']}")
    print(f"  Điểm xu hướng: {res['trend_score']}/6")
    print(f"  Cấu trúc: {res.get('last_struct','–')}")
    print(f"  TÍN HIỆU: {res['signal_str']}")
    if res['buy_signal'] or res['sell_signal']:
        from screener import format_vnd
        print(f"  ─ SL:  {format_vnd(res['sl'])} ({res['sl_pct']:+.1f}%)")
        print(f"  ─ TP1: {format_vnd(res['tp1'])} ({res['tp1_pct']:+.1f}%)")
        print(f"  ─ TP2: {format_vnd(res['tp2'])} ({res['tp2_pct']:+.1f}%)")
    print(f"{'='*60}\n")

    # Gửi Telegram
    msg = gdnl_bot.format_detail_message(res)
    sent = gdnl_bot.send_alert_to_default(msg)
    print(f"{'✅ Đã gửi về Telegram.' if sent else '⚠️ Không gửi được Telegram.'}")


def run_scan_mode():
    """Test quét toàn sàn, in kết quả."""
    print("\n🔍 Quét toàn sàn GDNL...")
    signals = gdnl_screener.run_gdnl_screener(signal_only=True)
    now_str = datetime.now().strftime("%H:%M %d/%m")
    summary = gdnl_bot.format_scan_summary(signals, f"[{now_str}]")
    print(summary)
    if signals:
        gdnl_bot.send_alert_to_default(summary)
        print(f"\n✅ Đã gửi {len(signals)} tín hiệu về Telegram.")


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] == "--listen":
        # Local daemon
        run_daemon_mode()

    elif args and args[0] == "--check" and len(args) >= 2:
        # Test 1 mã
        run_check_mode(args[1])

    elif args and args[0] == "--scan":
        # Test quét toàn sàn
        run_scan_mode()

    else:
        # GitHub Actions default mode
        run_github_actions_mode()
