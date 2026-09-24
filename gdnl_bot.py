# -*- coding: utf-8 -*-
"""
gdnl_bot.py — Telegram message handler cho Bot GDNL.
Chức năng:
  - Nhận lệnh /start, /help → hướng dẫn
  - Nhận mã cổ phiếu (3-5 ký tự) hoặc /soi <MÃ> → phân tích chi tiết
  - Nhận /scan → quét nhanh toàn sàn, gửi top tín hiệu
  - Nhận /status → trạng thái bot
"""

import os
import requests
import config
from screener import format_vnd


# ─────────────────────────────────────────────────────────────
# HELPER: GỬI TIN NHẮN TELEGRAM
# ─────────────────────────────────────────────────────────────

def _get_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", config.TELEGRAM_BOT_TOKEN)

def _get_default_chat() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", config.TELEGRAM_CHAT_ID)


def send_message(chat_id: str, text: str, parse_mode: str = "Markdown") -> bool:
    """Gửi tin nhắn Telegram. Trả về True nếu thành công."""
    token = _get_token()
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        print("[GDNL Bot] Token chưa được cấu hình.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }, timeout=10)
        if resp.status_code == 200:
            return True
        # Parse_mode fallback: nếu lỗi Markdown thì gửi plain text
        if resp.status_code == 400:
            resp2 = requests.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "",
            }, timeout=10)
            return resp2.status_code == 200
    except Exception as e:
        print(f"[GDNL Bot] Lỗi gửi Telegram: {e}")
    return False


def send_alert_to_default(text: str) -> bool:
    """Gửi cảnh báo về channel/chat mặc định (owner)."""
    return send_message(_get_default_chat(), text)


# ─────────────────────────────────────────────────────────────
# FORMAT TIN NHẮN
# ─────────────────────────────────────────────────────────────

def _pct_str(val: float) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%"


def format_detail_message(res: dict) -> str:
    """
    Format tin nhắn chi tiết 1 mã (khi user hỏi).
    Hiển thị đầy đủ: giá, xu hướng, MTF, ADX, cấu trúc, signal, kế hoạch.
    """
    sym    = res['symbol']
    ex     = res['exchange']
    comp   = config.get_company_info(sym)
    comp_name = comp.get('name') or comp.get('short_name') or ''
    title_sym = f"*{sym}: {comp_name}*" if comp_name else f"*{sym}*"

    price  = res['price_vnd']
    chg    = res['change_pct']
    score  = res['trend_score']
    sig    = res['signal_str']
    trend  = res['trend_label']
    cloud  = res['cloud_label']
    adx    = res['adx']
    dp     = res['di_plus']
    dm     = res['di_minus']
    vr     = res['vol_ratio']
    h1s    = res['mtf_h1_str']
    m30s   = res['mtf_m30_str']
    m5s    = res['mtf_m5_str']
    struct = res.get('last_struct', '')
    time_s = res.get('updated_time', '')

    buy  = res['buy_signal']
    sell = res['sell_signal']

    chg_icon = "🟢" if chg >= 0 else "🔴"
    sig_icon = "🟢" if buy else ("🔴" if sell else "⚪️")

    # Header
    msg = (
        f"📊 {title_sym} — `{ex}` | Điểm: `{score}/6`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ _{time_s}_\n"
        f"💰 Giá: `{price}` {chg_icon} `{_pct_str(chg)}`\n\n"
    )

    # Xu hướng
    msg += (
        f"📈 *Xu hướng:* {trend}\n"
        f"☁️ *Mây Ichimoku:* {cloud}\n"
        f"⚡️ *ADX:* `{adx}` | DI+: `{dp}` | DI-: `{dm}`\n"
        f"📊 *Khối lượng:* `{vr:.1f}x` MA20\n\n"
    )

    # MTF
    msg += (
        f"🕐 *MTF Đa Khung:*\n"
        f"  • H1 (dài hạn): {h1s}\n"
        f"  • M30 (trung hạn): {m30s}\n"
        f"  • M5 (ngắn hạn): {m5s}\n\n"
    )

    # Cấu trúc
    if struct:
        msg += f"🏗️ *Cấu trúc:* `{struct}`\n\n"

    # Tín hiệu
    msg += (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{sig_icon} *TÍN HIỆU: {sig}*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
    )

    # Kế hoạch giao dịch
    if buy or sell:
        sl   = format_vnd(res['sl'])
        tp1  = format_vnd(res['tp1'])
        tp2  = format_vnd(res['tp2'])
        sl_p = _pct_str(res['sl_pct'])
        t1_p = _pct_str(res['tp1_pct'])
        t2_p = _pct_str(res['tp2_pct'])
        action = "MUA" if buy else "BÁN"
        msg += (
            f"🎯 *KẾ HOẠCH ({action}):*\n"
            f"  • ENTRY: `{price}`\n"
            f"  • SL:    `{sl}` ({sl_p})\n"
            f"  • TP1:   `{tp1}` ({t1_p}) — _Dời SL hòa vốn_\n"
            f"  • TP2:   `{tp2}` ({t2_p}) — _Mục tiêu chính_\n\n"
            f"💡 _Quản trị rủi ro: Tối đa 2% NAV mỗi lệnh!_\n"
        )
    else:
        msg += f"👉 _Bot sẽ tự cảnh báo khi mã kích hoạt tín hiệu chuẩn._\n"

    return msg


def format_scan_summary(signals: list, time_str: str = "") -> str:
    """Format tin nhắn tóm tắt quét toàn sàn."""
    if not signals:
        return (
            f"🔍 *BOT GDNL — QUÉT TỰ ĐỘNG* {time_str}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⚪️ Không có mã nào đạt tín hiệu trong phiên này.\n"
            f"_Bot vẫn đang trực 24/7. Gõ tên mã để tra cứu riêng._"
        )

    msg = (
        f"🔥 *BOT GDNL — QUÉT TỰ ĐỘNG* {time_str}\n"
        f"Phát hiện *{len(signals)}* mã có tín hiệu:\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
    )

    for i, r in enumerate(signals[:10], 1):
        icon  = "🟢" if r['buy_signal'] else "🔴"
        sym   = r['symbol']
        sig   = r['signal_str']
        sc    = r['trend_score']
        price = r['price_vnd']
        chg   = r['change_pct']
        chg_s = f"+{chg:.1f}%" if chg >= 0 else f"{chg:.1f}%"
        msg += f"{i}. {icon} *{sym}* | {sig} | `{sc}/6` | `{price}` ({chg_s})\n"

    if len(signals) > 10:
        msg += f"\n_...và {len(signals) - 10} mã khác. Gõ tên mã để xem chi tiết._\n"

    msg += "\n💡 _Gõ tên mã bất kỳ (VD: `HPG`) để xem phân tích đầy đủ._"
    return msg


def format_welcome() -> str:
    """Tin nhắn chào mừng / hướng dẫn."""
    return (
        "🌊 *BOT GDNL — Vùng Xu Hướng PRO* 🌊\n"
        "────────────────────────\n"
        "Bot phân tích kỹ thuật TTCK Việt Nam dựa trên bộ chỉ báo:\n"
        "• SuperTrend + EMA 20/50\n"
        "• ADX/DMI lọc xu hướng\n"
        "• Cấu trúc BOS/CHoCH & Liquidity Sweep\n"
        "• Đa khung thời gian (MTF H1/M30/M5)\n"
        "• Điểm xu hướng 0–6\n\n"
        "📖 *CÁCH SỬ DỤNG:*\n"
        "• Gõ mã cổ phiếu (VD: `HPG`, `SSI`, `VCB`)\n"
        "• Hoặc `/soi HPG` hoặc `/check SSI`\n"
        "• `/scan` — Quét ngay toàn sàn\n"
        "• `/status` — Trạng thái bot\n\n"
        "🎯 *BỘ THÔNG SỐ TRẢ VỀ:*\n"
        "✅ Xu hướng SuperTrend + Mây Ichimoku\n"
        "✅ ADX, DI+, DI- (sức mạnh xu hướng)\n"
        "✅ Đa khung thời gian H1 / M30 / M5\n"
        "✅ Cấu trúc BOS / CHoCH / Sweep\n"
        "✅ Tín hiệu MUA/BÁN kèm SL, TP1, TP2\n\n"
        "👉 _Thử gõ ngay `HPG` hoặc `VCB` để xem kết quả!_"
    )


def format_status(in_session: bool) -> str:
    """Trạng thái bot."""
    session_str = "🟢 ĐANG TRONG GIỜ GIAO DỊCH" if in_session else "🔴 NGOÀI GIỜ GIAO DỊCH"
    return (
        f"🤖 *BOT GDNL — STATUS*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"• Trạng thái phiên: {session_str}\n"
        f"• Lịch quét: Mỗi 5 phút trong phiên\n"
        f"• Sàn: HOSE + HNX\n"
        f"• Chỉ báo: GDNL Vùng Xu Hướng PRO\n"
        f"• Score tối thiểu báo: {config.GDNL_MIN_SCORE}/6\n\n"
        f"_Gõ tên mã bất kỳ để phân tích ngay lập tức!_"
    )


# ─────────────────────────────────────────────────────────────
# POLLING & DISPATCH MESSAGES
# ─────────────────────────────────────────────────────────────

def get_pending_updates(offset: int = 0) -> list:
    """Lấy toàn bộ tin nhắn chưa xử lý từ Telegram."""
    token = _get_token()
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        resp = requests.get(url, params={
            "offset": offset,
            "timeout": 0,
            "limit": 100,
            "allowed_updates": ["message"],
        }, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("result", [])
    except Exception as e:
        print(f"[GDNL Bot] Lỗi getUpdates: {e}")
    return []


def ack_update(update_id: int):
    """Đánh dấu đã đọc bằng cách gọi getUpdates với offset = update_id + 1."""
    token = _get_token()
    try:
        requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": update_id + 1, "timeout": 0, "limit": 1},
            timeout=5
        )
    except Exception:
        pass


def process_updates(updates: list, run_scan_fn=None) -> int:
    """
    Xử lý danh sách updates từ Telegram.
    run_scan_fn: callable() → list of signal dicts (cho lệnh /scan)
    Trả về update_id lớn nhất đã xử lý.
    """
    from screener import is_trading_hour
    from gdnl_screener import analyze_single_symbol

    last_id = 0
    for update in updates:
        uid = update.get("update_id", 0)
        last_id = max(last_id, uid)

        msg = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        raw_text = msg.get("text", "").strip()
        if not raw_text or not chat_id:
            continue

        text_upper = raw_text.upper()
        parts = text_upper.split()
        cmd   = parts[0].split("@")[0] if parts else ""

        print(f"[GDNL Bot] Chat {chat_id}: {raw_text[:50]}")

        # /start, /help
        if cmd in ["/START", "/HELP", "/HUONGDAN"]:
            send_message(chat_id, format_welcome())
            continue

        # /status
        if cmd == "/STATUS":
            send_message(chat_id, format_status(is_trading_hour()))
            continue

        # /scan
        if cmd == "/SCAN":
            send_message(chat_id, "🔍 Đang quét toàn sàn... Vui lòng chờ 30-60 giây.")
            if run_scan_fn:
                try:
                    sigs = run_scan_fn()
                    from datetime import datetime
                    t = datetime.now().strftime("%H:%M %d/%m")
                    send_message(chat_id, format_scan_summary(sigs, f"[{t}]"))
                except Exception as e:
                    send_message(chat_id, f"❌ Lỗi quét: {e}")
            else:
                send_message(chat_id, "⚠️ Chức năng quét không khả dụng lúc này.")
            continue

        # /soi <MÃ> hoặc /check <MÃ>
        target = None
        if cmd in ["/SOI", "/CHECK"] and len(parts) > 1:
            target = parts[1]
        elif 2 <= len(text_upper) <= 5 and text_upper.isalpha():
            target = text_upper

        if target and 2 <= len(target) <= 5 and target.isalpha():
            try:
                res = analyze_single_symbol(target)
                if res:
                    send_message(chat_id, format_detail_message(res))
                else:
                    send_message(
                        chat_id,
                        f"❌ Không tìm thấy dữ liệu cho mã *{target}*.\n"
                        f"Vui lòng kiểm tra lại mã cổ phiếu!"
                    )
            except Exception as e:
                send_message(chat_id, f"❌ Lỗi phân tích {target}: {e}")
            continue

    return last_id
