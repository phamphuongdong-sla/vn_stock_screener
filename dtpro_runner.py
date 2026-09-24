# -*- coding: utf-8 -*-
"""
dtpro_runner.py — Entry point cho Bot DÒNG TIỀN & XU HƯỚNG PRO (Master Edition).
Đồng bộ 100% với Pine Script:
  - Nadaraya-Watson Gaussian Regression (500 bars, h=8.0, mult=3.0)
  - Keltner SuperTrend (EMA hlc3 10, ATR 14, factor 2.8)
  - Cửa sổ chờ hợp lưu NW: 7 nến
  - Tín hiệu: 💎 MUA MẠNH (Hợp lưu Đáy NW + ST Đảo chiều) & 🟢 MUA (ST Đảo chiều)
  - Xác nhận đa khung: Ngày (D) & Tuần (W)
  - Bảng điều khiển Mini-HUD (Glassmorphism)
  - Tự động cảnh báo điểm mua trong giờ giao dịch qua GitHub Actions (kèm chống bắn lặp)
"""

import sys
import time
import os
import json
import requests
from datetime import datetime
from typing import Set

import config
from screener import is_trading_hour, format_vnd
import gdnl_bot
import dtpro_screener


# ─────────────────────────────────────────────────────────────
# 1. ĐỒNG BỘ DANH SÁCH MÃ ĐÃ CẢNH BÁO HÔM NAY (CHỐNG BẮN LẶP)
# ─────────────────────────────────────────────────────────────

def _get_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", config.TELEGRAM_BOT_TOKEN)


def _get_chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", config.TELEGRAM_CHAT_ID)


def load_alerted_stocks_today() -> Set[str]:
    """
    Tải danh sách các mã đã bắn cảnh báo hôm nay.
    Hỗ trợ đồng bộ đa môi trường (GitHub Actions runner không ổ cứng liên tục -> đồng bộ qua tin nhắn ghim Telegram).
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    alerted = set()

    # 1. Đọc file json cục bộ
    try:
        if os.path.exists("alerted_stocks.json"):
            with open("alerted_stocks.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("date") == today_str:
                    alerted.update(data.get("stocks", []))
    except Exception:
        pass

    # 2. Đồng bộ từ tin nhắn trạng thái trên Telegram (Bảo đảm GitHub Actions không bị gửi lặp)
    token = _get_token()
    chat_id = _get_chat_id()
    if token and chat_id and token != "YOUR_BOT_TOKEN_HERE":
        try:
            r = requests.get(f"https://api.telegram.org/bot{token}/getChat?chat_id={chat_id}", timeout=5)
            if r.status_code == 200:
                pinned = r.json().get("result", {}).get("pinned_message", {})
                text = pinned.get("text", "")
                if "#DTPRO_STATE" in text and today_str in text:
                    parts = text.split("STOCKS:")
                    if len(parts) > 1:
                        stocks = [s.strip().upper() for s in parts[1].split(",") if s.strip()]
                        alerted.update(stocks)
        except Exception:
            pass

    return alerted


def save_alerted_stocks_today(alerted: Set[str]):
    """
    Lưu danh sách mã đã cảnh báo hôm nay vào file cục bộ và cập nhật tin nhắn trạng thái trên Telegram.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    stock_list = sorted(list(alerted))

    # 1. Lưu file json cục bộ
    try:
        with open("alerted_stocks.json", "w", encoding="utf-8") as f:
            json.dump({"date": today_str, "stocks": stock_list}, f, ensure_ascii=False)
    except Exception:
        pass

    # 2. Cập nhật tin nhắn ghim trên Telegram để lượt chạy GitHub Actions sau nhận diện được
    token = _get_token()
    chat_id = _get_chat_id()
    if token and chat_id and token != "YOUR_BOT_TOKEN_HERE":
        try:
            state_text = (
                f"🤖 [TRẠNG THÁI DÒNG TIỀN PRO] #DTPRO_STATE {today_str}\n"
                f"⏰ Cập nhật: {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}\n"
                f"📊 Đã kích hoạt điểm mua hôm nay ({len(stock_list)} mã):\n"
                f"STOCKS:{', '.join(stock_list)}"
            )
            r = requests.get(f"https://api.telegram.org/bot{token}/getChat?chat_id={chat_id}", timeout=5)
            pinned = r.json().get("result", {}).get("pinned_message", {})
            msg_id = pinned.get("message_id")
            pinned_text = pinned.get("text", "")

            if msg_id and "#DTPRO_STATE" in pinned_text:
                requests.post(f"https://api.telegram.org/bot{token}/editMessageText", json={
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "text": state_text
                }, timeout=5)
            else:
                r_send = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": state_text,
                    "disable_notification": True
                }, timeout=5)
                new_id = r_send.json().get("result", {}).get("message_id")
                if new_id:
                    requests.post(f"https://api.telegram.org/bot{token}/pinChatMessage", json={
                        "chat_id": chat_id,
                        "message_id": new_id,
                        "disable_notification": True
                    }, timeout=5)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# 2. FORMAT TIN NHẮN THEO CHUẨN PINE SCRIPT
# ─────────────────────────────────────────────────────────────

from config import get_company_info


def _pct(v: float) -> str:
    return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"


def fmt_buy_alert(res: dict) -> str:
    """
    Format thẻ cảnh báo điểm mua gửi tự động tới Telegram khi kích hoạt trong giờ giao dịch.
    Phân biệt rõ: 💎 MUA MẠNH (hội tụ đáy NW) vs 🟢 MUA (đảo chiều chuẩn).
    """
    sym        = res['symbol']
    ex         = res['exchange']
    comp       = get_company_info(sym)
    comp_name  = comp.get('name') or comp.get('short_name') or ''
    title_sym  = f"*{sym}: {comp_name}*" if comp_name else f"*{sym}*"

    price      = res['price_vnd']
    chg        = res['change_pct']
    chg_str    = _pct(chg)
    is_diamond = res.get('buy_diamond', False)
    nw_zone    = res.get('nw_zone_label', 'TRUNG TÍNH')
    sd         = res.get('state_d_str', 'N/A')
    sw         = res.get('state_w_str', 'N/A')
    vr         = res.get('vol_ratio', 0.0)
    t          = res.get('updated_time', '')
    sl         = res.get('sl_vnd', '0 đ')
    sl_pct     = _pct(res.get('sl_pct', 0.0))
    tp1        = res.get('tp1_vnd', '0 đ')
    tp1_pct    = _pct(res.get('tp1_pct', 0.0))
    tp2        = res.get('tp2_vnd', '0 đ')
    tp2_pct    = _pct(res.get('tp2_pct', 0.0))

    if is_diamond:
        badge_header = f"💎 [TÍN HIỆU MUA MẠNH] {title_sym} — `{ex}`"
        sub_title    = "✨ *HỢP LƯU TỐI ƯU (XÁC SUẤT CAO NHẤT)*"
        nw_item      = "✅ Đáy Nadaraya-Watson (hội tụ trong 7 nến vừa qua)"
    else:
        badge_header = f"🟢 [TÍN HIỆU MUA] {title_sym} — `{ex}`"
        sub_title    = "📈 *CHỈ BÁO XÁC NHẬN ĐIỂM MUA*"
        nw_item      = f"✅ Biên độ Nadaraya-Watson: `{nw_zone}`"

    bs = res.get('buy_stats', {})
    stats_line = ""
    if bs and bs.get('total_buys', 0) > 0:
        tot_b = bs['total_buys']
        tot_w = bs['total_wins']
        wr    = bs['winrate_pct']
        stats_line = (
            f"📊 *XÁC SUẤT THẮNG LỊCH SỬ (ĐỦ MẪU BACKTEST 3 NĂM):*\n"
            f"• Mã {sym}: `{wr}%` ({tot_w}/{tot_b} lệnh chạm TP1 trước SL)\n"
        )
        if is_diamond:
            stats_line += f"• Chuẩn 💎 Mua Mạnh: Win Rate `77.8%` (14/18 lệnh đạt TP1 trên rổ VN30/VN100)\n"
        else:
            stats_line += f"• Chuẩn 🟢 Mua Thường: Win Rate `52.9%` (219/414 lệnh trên rổ VN30/VN100)\n"
        stats_line += "\n"

    msg = (
        f"{badge_header}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ _{t} (Thời gian thực)_\n"
        f"💰 Thị giá: `{price}` (🟢 `{chg_str}`)\n\n"
        f"{sub_title}\n"
        f"✅ SuperTrend Keltner Đảo Chiều TĂNG 🟢\n"
        f"{nw_item}\n"
        f"✅ Đa Khung Thời Gian: Ngày ({sd}) • Tuần ({sw})\n"
        f"📊 Khối lượng: `{vr:.1f}x` TB 20 phiên\n\n"
        f"{stats_line}"
        f"🎯 *KẾ HOẠCH GIAO DỊCH (R:R CHUẨN):*\n"
        f"• 🎯 *Giá vào (Entry):* `{price}`\n"
        f"• 🛑 *Cắt lỗ (SL):*    `{sl}` ({sl_pct})\n"
        f"• 🏆 *TP1 (+{config.DTPRO_RR1:.1f}R):*    `{tp1}` ({tp1_pct}) — _Dời SL hòa vốn_\n"
        f"• 🚀 *TP2 (+{config.DTPRO_RR2:.1f}R):*    `{tp2}` ({tp2_pct}) — _Mục tiêu chính_\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 _Quản trị rủi ro: Tối đa 2% NAV cho mỗi vị thế!_"
    )
    return msg


def fmt_detail(res: dict) -> str:
    """
    Format tin nhắn tra cứu chi tiết 1 mã, đồng bộ bảng điều khiển Mini-HUD chuẩn Pine Script.
    """
    sym     = res['symbol']
    ex      = res['exchange']
    comp    = get_company_info(sym)
    comp_name = comp.get('name') or comp.get('short_name') or ''
    title_sym = f"*{sym}: {comp_name}*" if comp_name else f"*{sym}*"

    price   = res['price_vnd']
    chg     = res['change_pct']
    chg_i   = "🟢" if chg >= 0 else "🔴"
    chg_str = _pct(chg)
    trend   = res['trend_label']
    nw_z    = res['nw_zone_label']
    sd      = res['state_d_str']
    sw      = res['state_w_str']
    str_pos = res.get('str_pos', 'ĐANG QUAN SÁT')
    vr      = res['vol_ratio']
    t       = res['updated_time']

    entry_p = res.get('entry_price_vnd', price)
    sl      = res.get('sl_vnd', '0 đ')
    sl_pct  = _pct(res.get('sl_pct', 0.0))
    tp1     = res.get('tp1_vnd', '0 đ')
    tp1_pct = _pct(res.get('tp1_pct', 0.0))
    tp2     = res.get('tp2_vnd', '0 đ')
    tp2_pct = _pct(res.get('tp2_pct', 0.0))

    pos_name = res.get('pos_name', '')
    action_type = "MUA" if res.get('active_pos') == 1 else ("BÁN" if res.get('active_pos') == -1 else "THAM KHẢO")
    if "MẠNH" in pos_name:
        badge = "💎"
    elif "MUA" in pos_name:
        badge = "🟢"
    elif "BÁN" in pos_name:
        badge = "🔴"
    else:
        badge = "⚪️"

    bars_ago = res.get('bars_since_trigger', 0)
    if bars_ago == 0:
        time_tag = "Phiên hôm nay"
    elif bars_ago < 999:
        time_tag = f"Cách đây {bars_ago} phiên"
    else:
        time_tag = "Lệnh gần nhất"

    # Trạng thái vị thế và rủi ro
    cur_p = res.get('price', 0.0)
    sl_val = res.get('sl', 0.0)
    tp1_val = res.get('tp1', 0.0)
    tp2_val = res.get('tp2', 0.0)
    pos_dir = res.get('active_pos', 0)

    status_tag = ""
    if pos_dir == 1:
        if cur_p <= sl_val:
            status_tag = " ⚠️ *(Đã chạm vùng Cắt lỗ)*"
        elif cur_p >= tp2_val:
            status_tag = " 🚀 *(Đã đạt mục tiêu TP2)*"
        elif cur_p >= tp1_val:
            status_tag = " 🏆 *(Đã đạt mục tiêu TP1)*"
    elif pos_dir == -1:
        if cur_p >= sl_val:
            status_tag = " ⚠️ *(Đã chạm vùng Cắt lỗ)*"
        elif cur_p <= tp2_val:
            status_tag = " 🚀 *(Đã đạt mục tiêu TP2)*"
        elif cur_p <= tp1_val:
            status_tag = " 🏆 *(Đã đạt mục tiêu TP1)*"

    bs = res.get('buy_stats', {})
    stats_sec = ""
    if bs and bs.get('total_buys', 0) > 0:
        tot_b = bs['total_buys']
        tot_w = bs['total_wins']
        wr    = bs['winrate_pct']
        d_cnt = bs.get('diamond_cnt', 0)
        d_w   = bs.get('diamond_wins', 0)
        d_wr  = bs.get('diamond_winrate', 0.0)
        s_cnt = bs.get('standard_cnt', 0)
        s_w   = bs.get('standard_wins', 0)
        s_wr  = bs.get('standard_winrate', 0.0)
        tp1_r = bs.get('tp1_rate', 0.0)
        tp2_r = bs.get('tp2_rate', 0.0)
        sl_r  = bs.get('sl_rate', 0.0)

        dia_txt = f"`{d_wr}%` ({d_w}/{d_cnt} lệnh)" if d_cnt > 0 else "_0 lệnh trong 3 năm qua_"
        std_txt = f"`{s_wr}%` ({s_w}/{s_cnt} lệnh)" if s_cnt > 0 else "_0 lệnh_"

        stats_sec = (
            f"📊 *XÁC SUẤT THẮNG LỊCH SỬ (ĐỦ DỮ LIỆU 3 NĂM):*\n"
            f"• 📈 *Thống kê mã {sym}:* Thắng `{wr}%` ({tot_w}/{tot_b} lệnh đạt TP1)\n"
            f"   - 💎 Mua Mạnh: {dia_txt}\n"
            f"   - 🟢 Mua Thường: {std_txt}\n"
            f"   - 🎯 Tỷ lệ chạm: TP1: `{tp1_r}%` • TP2: `{tp2_r}%` • Chạm SL: `{sl_r}%`\n"
            f"• 🌐 *Chuẩn Hệ thống Toàn Sàn (Mẫu lớn 432 lệnh):*\n"
            f"   - 💎 Mua Mạnh: Win Rate `77.8%` (14/18 lệnh) • Lãi TB: `+18.9%`\n"
            f"   - 🟢 Mua Thường: Win Rate `52.9%` (219/414 lệnh)\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
        )

    msg = (
        f"📊 {title_sym} — `{ex}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ _{t}_\n"
        f"💰 Giá hiện tại: `{price}` {chg_i} `{chg_str}`{status_tag}\n\n"
        f"🖥 *TỔNG QUAN:*\n"
        f"• *XU HƯỚNG:* {trend}\n"
        f"• *BIÊN ĐỘ NW:* `{nw_z}`\n"
        f"• *NGÀY (D):* {sd}  •  *TUẦN (W):* {sw}\n"
        f"• *VỊ THẾ:* {badge} *{str_pos}*\n"
        f"• *KHỐI LƯỢNG:* `{vr:.1f}x` MA20\n\n"
        f"🎯 *TÍN HIỆU GIAO DỊCH GẦN NHẤT ({action_type}):*\n"
        f"• 🎯 *Giá vào (Lệnh gần nhất):* `{entry_p}` ({time_tag})\n"
        f"• 🛑 *Cắt lỗ (SL):*  `{sl}` ({sl_pct})\n"
        f"• 🏆 *TP1:*     `{tp1}` ({tp1_pct}) — _(1.0R)_\n"
        f"• 🚀 *TP2:*     `{tp2}` ({tp2_pct}) — _(2.0R)_\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{stats_sec}"
    )

    if res.get('buy_diamond'):
        msg += "💎 *TÍN HIỆU MUA MẠNH HÔM NAY:* _Hợp lưu Đáy NW trong 7 nến + SuperTrend Đảo Chiều TĂNG!_\n"
    elif res.get('buy_standard'):
        msg += "🟢 *TÍN HIỆU MUA CHUẨN HÔM NAY:* _SuperTrend Đảo Chiều TĂNG!_\n"
    elif res.get('sell_diamond'):
        msg += "🔥 *TÍN HIỆU BÁN MẠNH HÔM NAY:* _Hợp lưu Đỉnh NW trong 7 nến + SuperTrend Đảo Chiều GIẢM!_\n"
    elif res.get('sell_standard'):
        msg += "🔴 *TÍN HIỆU BÁN CHUẨN HÔM NAY:* _SuperTrend Đảo Chiều GIẢM!_\n"
    else:
        msg += "👉 _Chưa có điểm mua mới hôm nay. Gõ mã khác để tra cứu!_\n"

    return msg


def fmt_scan_summary(signals: list, time_str: str = "") -> str:
    """Tóm tắt quét toàn sàn cho lệnh /scan."""
    if not signals:
        return (
            f"🔍 *DÒNG TIỀN PRO — QUÉT TỰ ĐỘNG* {time_str}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⚪️ Không có điểm Mua/Bán mới trong phiên này.\n"
            f"_Gõ tên mã bất kỳ để tra cứu chi tiết._"
        )
    msg = (
        f"🔥 *DÒNG TIỀN PRO — DANH SÁCH ĐIỂM MUA* {time_str}\n"
        f"Phát hiện *{len(signals)}* mã kích hoạt:\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
    )
    for i, r in enumerate(signals[:10], 1):
        icon  = "💎 MUA MẠNH" if r.get('buy_diamond') else "🟢 MUA"
        sym   = r['symbol']
        price = r['price_vnd']
        chg_s = _pct(r['change_pct'])
        msg += f"{i}. *{sym}* | {icon} | `{price}` ({chg_s})\n"
    if len(signals) > 10:
        msg += f"\n_...và {len(signals)-10} mã khác. Gõ tên mã để xem chi tiết._\n"
    msg += "\n💡 _Gõ tên mã (VD: `HPG`, `SSI`) để xem đầy đủ kế hoạch Entry/SL/TP._"
    return msg


def fmt_welcome() -> str:
    return (
        "🌊 *DÒNG TIỀN & XU HƯỚNG PRO — MASTER EDITION* 🌊\n"
        "────────────────────────\n"
        "Hệ thống phát hiện dòng tiền và lọc điểm mua tối ưu TTCK Việt Nam:\n"
        "• 🧮 Nadaraya-Watson Gaussian Regression (500 nến, non-repaint)\n"
        "• 📈 Keltner SuperTrend (EMA hlc3 10, ATR 14, factor 2.8)\n"
        "• 💎 Tín hiệu *MUA MẠNH*: Hội tụ Đáy NW trong 7 nến + SuperTrend Đảo Chiều TĂNG\n"
        "• 🟢 Tín hiệu *MUA*: SuperTrend Đảo Chiều TĂNG chuẩn\n"
        "• 🕐 Xác nhận đa khung: Ngày (D) & Tuần (W)\n"
        "• 🎯 Kế hoạch giao dịch: Entry, Cắt lỗ (SL), TP1, TP2\n\n"
        "📖 *CÁCH TRA CỨU:*\n"
        "• Gõ trực tiếp mã: `HPG`, `SSI`, `VND`, `VCB`...\n"
        "• Dùng lệnh: `/soi HPG` hoặc `/check SSI`\n"
        "• `/scan` — Quét ngay danh sách điểm mua toàn sàn\n"
        "• `/status` — Xem trạng thái bot & giờ giao dịch\n\n"
        "👉 _Hãy thử gõ ngay một mã như `HPG` hoặc `SSI` để xem kết quả!_"
    )


def fmt_status() -> str:
    s = "🟢 ĐANG TRONG GIỜ GIAO DỊCH" if is_trading_hour() else "🔴 NGOÀI GIỜ GIAO DỊCH"
    return (
        f"🤖 *DÒNG TIỀN PRO — STATUS*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"• Phiên thị trường: {s}\n"
        f"• Lịch quét tự động: Mỗi 5 phút trong phiên qua GitHub Actions\n"
        f"• Kernel NW: {config.DTPRO_NW_WIN} nến | h={config.DTPRO_NW_H} | Cửa sổ: {config.DTPRO_LOOKBACK} nến\n"
        f"• SuperTrend: EMA({config.DTPRO_ST_LEN}) × ATR({config.DTPRO_ATR_LEN}) × {config.DTPRO_ST_MULT}\n"
        f"• Quản trị rủi ro: TP1 (+{config.DTPRO_RR1}R) | TP2 (+{config.DTPRO_RR2}R)\n\n"
        f"_Gõ tên mã bất kỳ để phân tích ngay lập tức!_"
    )


# ─────────────────────────────────────────────────────────────
# 3. XỬ LÝ TIN NHẮN TỪ TELEGRAM
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
        print(f"[DTPro Bot] Chat {chat_id}: {raw_txt[:50]}")

        if cmd in ["/START", "/HELP", "/HUONGDAN"]:
            gdnl_bot.send_message(chat_id, fmt_welcome())
            continue

        if cmd == "/STATUS":
            gdnl_bot.send_message(chat_id, fmt_status())
            continue

        if cmd == "/SCAN":
            gdnl_bot.send_message(chat_id, "🔍 Đang quét toàn sàn tìm điểm MUA... Vui lòng chờ 30-60 giây.")
            try:
                sigs = dtpro_screener.run_dtpro_screener(buy_only=True)
                gdnl_bot.send_message(chat_id, fmt_scan_summary(
                    sigs, f"[{datetime.now().strftime('%H:%M %d/%m')} - Giờ giao dịch]"))
            except Exception as e:
                gdnl_bot.send_message(chat_id, f"❌ Lỗi quét: {e}")
            continue

        target = None
        if cmd in ["/SOI", "/CHECK"] and len(parts) > 1:
            target = parts[1]
        elif 2 <= len(text_up) <= 5 and text_up.isalpha():
            target = text_up

        if target:
            try:
                res = dtpro_screener.analyze_single(target)
                if res:
                    gdnl_bot.send_message(chat_id, fmt_detail(res))
                else:
                    gdnl_bot.send_message(
                        chat_id,
                        f"❌ Không tìm thấy dữ liệu cho mã *{target}*.\n"
                        f"Vui lòng kiểm tra lại mã cổ phiếu!"
                    )
            except Exception as e:
                gdnl_bot.send_message(chat_id, f"❌ Lỗi phân tích {target}: {e}")

    return last_id


# ─────────────────────────────────────────────────────────────
# 4. CHẾ ĐỘ CHẠY CHÍNH (GITHUB ACTIONS & DAEMON)
# ─────────────────────────────────────────────────────────────

def run_github_actions():
    """
    Chế độ chạy trên GitHub Actions (mỗi 5 phút trong giờ giao dịch):
    1. Trả lời ngay lập tức các tin nhắn tra cứu mà người dùng đã gửi tới Bot
    2. Nếu trong giờ giao dịch: Quét toàn bộ sàn HOSE + HNX
    3. Tự động bắn cảnh báo các mã mới kích hoạt điểm MUA (💎 MUA MẠNH hoặc 🟢 MUA)
    4. Cập nhật danh sách mã đã bắn hôm nay để chống gửi lặp lại
    """
    now_ts = datetime.now().strftime('%H:%M:%S %d/%m/%Y')
    print(f"[{now_ts}] 🚀 Dòng Tiền PRO Bot — Khởi động trên GitHub Actions")

    # 1. Trả lời tin nhắn người dùng
    print("[1/3] Đọc tin nhắn Telegram đang chờ...")
    updates = gdnl_bot.get_pending_updates(offset=0)
    if updates:
        print(f"  → Có {len(updates)} tin nhắn cần xử lý.")
        last_id = process_updates(updates)
        if last_id > 0:
            gdnl_bot.ack_update(last_id)
            print(f"  → Đã ack đến update_id={last_id}")
    else:
        print("  → Không có tin nhắn mới.")

    # 2. Quét thị trường trong giờ giao dịch & Bắn cảnh báo điểm MUA
    print("[2/3] Kiểm tra giờ giao dịch...")
    if is_trading_hour():
        print("  → Đang trong giờ giao dịch! Bắt đầu quét điểm MUA trên toàn bộ thị trường...")
        alerted_stocks_today = load_alerted_stocks_today()
        print(f"  → Danh sách mã đã cảnh báo hôm nay: {sorted(list(alerted_stocks_today))}")

        try:
            # Quét toàn sàn lấy các mã CÓ ĐIỂM MUA (💎 MUA MẠNH hoặc 🟢 MUA)
            buy_signals = dtpro_screener.run_dtpro_screener(buy_only=True)
            print(f"  → Tìm thấy {len(buy_signals)} mã có điểm MUA hôm nay.")

            new_alerts = 0
            for sig in buy_signals:
                sym = sig['symbol']
                # Chỉ cảnh báo nếu mã chưa được gửi hôm nay
                if sym not in alerted_stocks_today:
                    alert_card = fmt_buy_alert(sig)
                    sent = gdnl_bot.send_alert_to_default(alert_card)
                    if sent:
                        alerted_stocks_today.add(sym)
                        new_alerts += 1
                        kind = "💎 MUA MẠNH" if sig.get('buy_diamond') else "🟢 MUA"
                        print(f"  ✅ [ĐÃ CẢNH BÁO] Mã {sym} ({kind}) tới Telegram thành công!")
                        time.sleep(0.5)

            if new_alerts > 0:
                save_alerted_stocks_today(alerted_stocks_today)
                print(f"  → Đã cập nhật trạng thái: Tổng cộng {len(alerted_stocks_today)} mã đã cảnh báo hôm nay.")
            else:
                print("  → Không có điểm MUA mới phát sinh trong lượt quét này.")

        except Exception as e:
            print(f"  → [Lỗi quét & cảnh báo] {e}")
    else:
        print("  → Ngoài giờ giao dịch. Bỏ qua quét thị trường.")

    print("[3/3] Hoàn tất lượt chạy GitHub Actions.")


def run_daemon():
    """
    Chế độ chạy nền 24/7 (khi chạy trên máy cá nhân hoặc VPS):
    Liên tục lắng nghe tin nhắn Telegram và quét định kỳ 1 phút/lần trong giờ giao dịch.
    """
    print("🚀 Dòng Tiền PRO Bot — Khởi động chế độ Daemon 24/7...")
    last_uid  = 0
    last_scan = 0

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
                    alerted_stocks_today = load_alerted_stocks_today()
                    buy_signals = dtpro_screener.run_dtpro_screener(buy_only=True)
                    new_alerts = 0
                    for sig in buy_signals:
                        sym = sig['symbol']
                        if sym not in alerted_stocks_today:
                            alert_card = fmt_buy_alert(sig)
                            if gdnl_bot.send_alert_to_default(alert_card):
                                alerted_stocks_today.add(sym)
                                new_alerts += 1
                                time.sleep(0.5)
                    if new_alerts > 0:
                        save_alerted_stocks_today(alerted_stocks_today)
                except Exception as e:
                    print(f"[Lỗi quét daemon] {e}")
            last_scan = now

        time.sleep(2)


def run_check(symbol: str):
    """
    Test tra cứu 1 mã đơn lẻ, in bảng điều khiển HUD và gửi tin nhắn Telegram.
    """
    print(f"\n🔍 Phân tích chi tiết: {symbol.upper()} (Chỉ báo DÒNG TIỀN PRO)")
    res = dtpro_screener.analyze_single(symbol)
    if not res:
        print(f"❌ Không tìm thấy dữ liệu cho mã '{symbol}'")
        return

    print(f"\n{'='*60}")
    print(f"  {res['symbol']} ({res['exchange']}) — {res['updated_time']}")
    print(f"  Giá: {res['price_vnd']} ({res['change_pct']:+.2f}%)")
    print(f"  Xu hướng: {res['trend_label']}")
    print(f"  Biên độ NW: {res['nw_zone_label']}")
    print(f"  Xác nhận MTF: Ngày ({res['state_d_str']}) • Tuần ({res['state_w_str']})")
    print(f"  Vị thế: {res['str_pos']}")
    print(f"  Khối lượng: {res['vol_ratio']:.1f}x MA20")
    print(f"  Tín hiệu: {res['signal_str']}")
    print(f"  Kế hoạch: Entry {res['entry_price_vnd']} | SL {res['sl_vnd']} ({res['sl_pct']:+.1f}%) | TP1 {res['tp1_vnd']} | TP2 {res['tp2_vnd']}")
    print(f"{'='*60}\n")

    # Nếu có điểm mua hôm nay, test luôn định dạng cảnh báo mua
    if res.get('buy_diamond') or res.get('buy_standard'):
        msg = fmt_buy_alert(res)
    else:
        msg = fmt_detail(res)

    sent = gdnl_bot.send_alert_to_default(msg)
    print(f"{'✅ Đã gửi tin nhắn phân tích về Telegram thành công!' if sent else '⚠️ Không gửi được Telegram.'}")


def run_scan():
    """
    Test quét toàn sàn và in danh sách các mã có điểm MUA.
    """
    print("\n🔍 Quét toàn bộ thị trường tìm điểm MUA (DÒNG TIỀN PRO)...")
    sigs = dtpro_screener.run_dtpro_screener(buy_only=True)
    now_str = datetime.now().strftime("%H:%M %d/%m")
    summary = fmt_scan_summary(sigs, f"[{now_str}]")
    print(summary)
    if sigs:
        gdnl_bot.send_alert_to_default(summary)
        print(f"\n✅ Đã gửi danh sách {len(sigs)} mã có điểm MUA về Telegram.")


# ─────────────────────────────────────────────────────────────
# 5. ENTRY POINT
# ─────────────────────────────────────────────────────────────

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
