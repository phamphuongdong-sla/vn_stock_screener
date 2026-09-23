# -*- coding: utf-8 -*-
"""
dtpro_runner.py — Entry point cho Bot DÒNG TIỀN & XU HƯỚNG PRO.

Modes:
  python dtpro_runner.py               → GitHub Actions (scan + reply)
  python dtpro_runner.py --check HPG   → Test 1 mã
  python dtpro_runner.py --scan        → Test quét toàn sàn
  python dtpro_runner.py --listen      → Daemon 24/7 local
"""

import sys
import time
import os
from datetime import datetime

import config
from screener import is_trading_hour
import gdnl_bot          # Tái sử dụng send_message, get_pending_updates, ack_update
import dtpro_screener
from screener import format_vnd


# ─────────────────────────────────────────────────────────────
# FORMAT TIN NHẮN DÒNG TIỀN PRO
# ─────────────────────────────────────────────────────────────

def _pct(v: float) -> str:
    return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"


def fmt_detail(res: dict) -> str:
    """Tin nhắn chi tiết 1 mã."""
    sym   = res['symbol'];    ex    = res['exchange']
    price = res['price_vnd']; chg   = res['change_pct']
    trend = res['trend_label']
    nw_z  = res['nw_zone_label']
    sd    = res['state_d_str']; sw = res['state_w_str']
    sig   = res['signal_str'];  vr = res['vol_ratio']
    t     = res['updated_time']

    is_buy  = res['is_buy']
    is_sell = res['is_sell']
    chg_i   = "🟢" if chg >= 0 else "🔴"
    sig_i   = "💎" if (res['buy_diamond'] or res['sell_diamond']) else \
              ("🟢" if is_buy else ("🔴" if is_sell else "⚪️"))

    msg = (
        f"📊 *{sym}* — `{ex}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ _{t}_\n"
        f"💰 Giá: `{price}` {chg_i} `{_pct(chg)}`\n\n"
        f"📈 *Xu hướng:* {trend}\n"
        f"🌊 *Biên NW:* {nw_z}\n"
        f"📊 *Khối lượng:* `{vr:.1f}x` MA20\n\n"
        f"🕐 *MTF Xác Nhận:*\n"
        f"  • Ngày (D): {sd}\n"
        f"  • Tuần (W): {sw}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{sig_i} *TÍN HIỆU: {sig}*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
    )

    if is_buy or is_sell:
        action = "MUA 📈" if is_buy else "BÁN 📉"
        msg += (
            f"🎯 *KẾ HOẠCH {action}:*\n"
            f"  • ENTRY: `{price}`\n"
            f"  • SL:    `{format_vnd(res['sl'])}` ({_pct(res['sl_pct'])})\n"
            f"  • TP1:   `{format_vnd(res['tp1'])}` ({_pct(res['tp1_pct'])}) — _Dời SL hòa vốn_\n"
            f"  • TP2:   `{format_vnd(res['tp2'])}` ({_pct(res['tp2_pct'])}) — _Mục tiêu chính_\n\n"
            f"💡 _Quản trị rủi ro: Tối đa 2% NAV mỗi lệnh!_\n"
        )
        if res.get('buy_diamond') or res.get('sell_diamond'):
            msg += "✨ _Hội tụ tối ưu: SuperTrend đảo chiều tại biên NW — xác suất cao nhất!_\n"
    else:
        msg += "👉 _Bot tự cảnh báo khi tín hiệu kích hoạt. Gõ mã bất kỳ để tra cứu!_\n"

    return msg


def fmt_summary(signals: list, time_str: str = "") -> str:
    """Tóm tắt quét toàn sàn."""
    if not signals:
        return (
            f"🔍 *DÒNG TIỀN PRO — QUÉT TỰ ĐỘNG* {time_str}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⚪️ Không có tín hiệu trong phiên này.\n"
            f"_Gõ tên mã để tra cứu riêng._"
        )
    msg = (
        f"🔥 *DÒNG TIỀN PRO — QUÉT TỰ ĐỘNG* {time_str}\n"
        f"Phát hiện *{len(signals)}* mã có tín hiệu:\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
    )
    for i, r in enumerate(signals[:10], 1):
        icon = ("💎" if r.get('buy_diamond') or r.get('sell_diamond') else
                ("🟢" if r['is_buy'] else "🔴"))
        sym   = r['symbol'];  sig = r['signal_str']
        price = r['price_vnd']
        chg_s = _pct(r['change_pct'])
        msg += f"{i}. {icon} *{sym}* | {sig} | `{price}` ({chg_s})\n"
    if len(signals) > 10:
        msg += f"\n_...và {len(signals)-10} mã khác. Gõ tên mã để xem chi tiết._\n"
    msg += "\n💡 _Gõ tên mã (VD: `HPG`) để xem phân tích đầy đủ._"
    return msg


def fmt_welcome() -> str:
    return (
        "🌊 *DÒNG TIỀN & XU HƯỚNG PRO — MASTER EDITION* 🌊\n"
        "────────────────────────\n"
        "Bot phân tích TTCK Việt Nam dựa trên:\n"
        "• 🧮 Nadaraya-Watson Gaussian Regression (non-repaint)\n"
        "• 📈 Keltner SuperTrend (EMA hlc3 + ATR)\n"
        "• 🕐 Xác nhận đa khung: Ngày (D) & Tuần (W)\n"
        "• 💎 Tín hiệu Diamond khi hội tụ NW + SuperTrend\n\n"
        "📖 *CÁCH DÙNG:*\n"
        "• Gõ mã cổ phiếu: `HPG`, `SSI`, `VCB`...\n"
        "• `/soi HPG` hoặc `/check VCB`\n"
        "• `/scan` — Quét ngay toàn sàn\n"
        "• `/status` — Trạng thái bot\n\n"
        "🎯 *Tín hiệu mạnh nhất (💎 Diamond):*\n"
        "_SuperTrend đảo chiều ĐÚNG tại biên NW — hội tụ xác suất cao nhất!_\n\n"
        "👉 _Thử gõ `HPG` hoặc `VCB` ngay!_"
    )


def fmt_status() -> str:
    from screener import is_trading_hour
    s = "🟢 ĐANG TRONG GIỜ GIAO DỊCH" if is_trading_hour() else "🔴 NGOÀI GIỜ GIAO DỊCH"
    return (
        f"🤖 *DÒNG TIỀN PRO — STATUS*\n━━━━━━━━━━━━━━━━━━━\n"
        f"• Trạng thái: {s}\n"
        f"• Kernel NW: {config.DTPRO_NW_WIN} nến | h={config.DTPRO_NW_H}\n"
        f"• SuperTrend: EMA({config.DTPRO_ST_LEN}) × ATR({config.DTPRO_ATR_LEN}) × {config.DTPRO_ST_MULT}\n"
        f"• TP1: {config.DTPRO_RR1}R | TP2: {config.DTPRO_RR2}R\n"
        f"_Gõ tên mã bất kỳ để phân tích!_"
    )


# ─────────────────────────────────────────────────────────────
# PROCESS TELEGRAM UPDATES
# ─────────────────────────────────────────────────────────────

def process_updates(updates: list) -> int:
    last_id = 0
    for update in updates:
        uid = update.get("update_id", 0)
        last_id = max(last_id, uid)
        msg     = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        raw_txt = msg.get("text", "").strip()
        if not raw_txt or not chat_id:
            continue

        text_up = raw_txt.upper()
        parts   = text_up.split()
        cmd     = parts[0].split("@")[0] if parts else ""
        print(f"[DTPro Bot] {chat_id}: {raw_txt[:50]}")

        if cmd in ["/START", "/HELP"]:
            gdnl_bot.send_message(chat_id, fmt_welcome())
            continue
        if cmd == "/STATUS":
            gdnl_bot.send_message(chat_id, fmt_status())
            continue
        if cmd == "/SCAN":
            gdnl_bot.send_message(chat_id, "🔍 Đang quét toàn sàn... Vui lòng chờ 60-90 giây.")
            try:
                sigs = dtpro_screener.run_dtpro_screener(signal_only=True)
                gdnl_bot.send_message(chat_id, fmt_summary(
                    sigs, f"[{datetime.now().strftime('%H:%M %d/%m')}]"))
            except Exception as e:
                gdnl_bot.send_message(chat_id, f"❌ Lỗi quét: {e}")
            continue

        target = None
        if cmd in ["/SOI", "/CHECK"] and len(parts) > 1:
            target = parts[1]
        elif 2 <= len(text_up) <= 5 and text_up.isalpha():
            target = text_up

        if target:
            gdnl_bot.send_message(chat_id, f"🔍 Đang phân tích *{target}*... (NW 500 nến)")
            try:
                res = dtpro_screener.analyze_single(target)
                gdnl_bot.send_message(chat_id,
                    fmt_detail(res) if res else
                    f"❌ Không tìm thấy dữ liệu cho mã *{target}*.")
            except Exception as e:
                gdnl_bot.send_message(chat_id, f"❌ Lỗi phân tích {target}: {e}")

    return last_id


# ─────────────────────────────────────────────────────────────
# RUN MODES
# ─────────────────────────────────────────────────────────────

def run_github_actions():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Dòng Tiền PRO Bot (GitHub Actions)")

    print("[1/3] Đọc tin nhắn Telegram...")
    updates = gdnl_bot.get_pending_updates(offset=0)
    if updates:
        print(f"  → {len(updates)} tin nhắn cần xử lý.")
        last_id = process_updates(updates)
        if last_id > 0:
            gdnl_bot.ack_update(last_id)
    else:
        print("  → Không có tin nhắn mới.")

    print("[2/3] Kiểm tra giờ giao dịch...")
    if is_trading_hour():
        print("  → Trong giờ giao dịch. Quét toàn sàn...")
        try:
            signals = dtpro_screener.run_dtpro_screener(signal_only=True)
            now_str = datetime.now().strftime("%H:%M %d/%m")
            summary = fmt_summary(signals, f"[{now_str}]")
            if signals:
                gdnl_bot.send_alert_to_default(summary)
                print(f"  → Gửi {len(signals)} tín hiệu về Telegram.")
            else:
                print("  → Không có tín hiệu.")
        except Exception as e:
            print(f"  → [Lỗi quét] {e}")
    else:
        print("  → Ngoài giờ giao dịch. Bỏ qua quét.")

    print("[3/3] Hoàn tất.")


def run_daemon():
    print("🚀 Dòng Tiền PRO Bot (Daemon 24/7)...")
    last_uid   = 0
    last_scan  = 0
    while True:
        try:
            updates = gdnl_bot.get_pending_updates(offset=last_uid + 1)
            if updates:
                last_uid = process_updates(updates)
        except Exception as e:
            print(f"[Lỗi polling] {e}")

        now = time.time()
        if now - last_scan >= config.SCAN_INTERVAL_SECONDS:
            if is_trading_hour():
                try:
                    sigs = dtpro_screener.run_dtpro_screener(signal_only=True)
                    if sigs:
                        gdnl_bot.send_alert_to_default(
                            fmt_summary(sigs, f"[{datetime.now().strftime('%H:%M %d/%m')}]"))
                except Exception as e:
                    print(f"[Lỗi quét] {e}")
            last_scan = now
        time.sleep(2)


def run_check(symbol: str):
    print(f"\n🔍 Phân tích: {symbol.upper()} (DTPro, NW {config.DTPRO_NW_WIN} nến)")
    res = dtpro_screener.analyze_single(symbol)
    if not res:
        print(f"❌ Không tìm thấy dữ liệu cho '{symbol}'")
        return
    print(f"\n{'='*60}")
    print(f"  {res['symbol']} ({res['exchange']}) — {res['updated_time']}")
    print(f"  Giá: {res['price_vnd']} ({res['change_pct']:+.2f}%)")
    print(f"  Xu hướng: {res['trend_label']}")
    print(f"  NW Zone: {res['nw_zone_label']}")
    print(f"  MTF — D: {res['state_d_str']} | W: {res['state_w_str']}")
    print(f"  Volume: {res['vol_ratio']:.1f}x MA20")
    print(f"  TÍN HIỆU: {res['signal_str']}")
    print(f"  NW bars used: {res.get('nw_bars_used', '?')}")
    if res['is_buy'] or res['is_sell']:
        print(f"  SL:  {format_vnd(res['sl'])} ({res['sl_pct']:+.1f}%)")
        print(f"  TP1: {format_vnd(res['tp1'])} ({res['tp1_pct']:+.1f}%)")
        print(f"  TP2: {format_vnd(res['tp2'])} ({res['tp2_pct']:+.1f}%)")
    print(f"{'='*60}\n")
    sent = gdnl_bot.send_alert_to_default(fmt_detail(res))
    print(f"{'✅ Đã gửi Telegram.' if sent else '⚠️ Không gửi được Telegram.'}")


def run_scan():
    print("\n🔍 Quét toàn sàn (DTPro)...")
    sigs    = dtpro_screener.run_dtpro_screener(signal_only=True)
    now_str = datetime.now().strftime("%H:%M %d/%m")
    summary = fmt_summary(sigs, f"[{now_str}]")
    print(summary)
    if sigs:
        gdnl_bot.send_alert_to_default(summary)
        print(f"\n✅ Gửi {len(sigs)} tín hiệu về Telegram.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--listen":
        run_daemon()
    elif args and args[0] == "--check" and len(args) >= 2:
        run_check(args[1])
    elif args and args[0] == "--scan":
        run_scan()
    else:
        run_github_actions()
