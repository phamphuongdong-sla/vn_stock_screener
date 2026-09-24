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


def _confidence_label(n: int) -> str:
    """Phân loại độ tin cậy theo cỡ mẫu (theo spec)."""
    if n < 5:
        return "⚪ CHƯA ĐỦ DỮ LIỆU"
    elif n < 10:
        return "🔴 MẪU NHỎ"
    elif n < 20:
        return "🟠 DỮ LIỆU HẠN CHẾ"
    elif n < 50:
        return "🟡 DỮ LIỆU KHÁ"
    else:
        return "🟢 DỮ LIỆU ĐỦ LỚN"


def fmt_stats_block(sym: str, bs: dict) -> str:
    """Format bảng thống kê 5 năm lịch sử trực quan theo từng vùng chỉ báo trên Khung Ngày."""
    if not bs or bs.get('total_buys', 0) <= 0:
        return ""
    
    tot = bs.get('total_buys', 0)
    tot_w = bs.get('tot_wins', 0)
    tot_l = tot - tot_w
    tot_wr = bs.get('tot_winrate', 0.0)

    # Vùng Mua Mạnh (Diamond)
    n_dia = bs.get('n_buy_diamond', 0)
    dia_w = bs.get('dia_wins', 0)
    dia_l = n_dia - dia_w
    dia_wr = bs.get('dia_winrate', 0.0)

    # Vùng Mua Chuẩn (Standard)
    n_std = bs.get('n_buy', 0)
    std_w = bs.get('std_wins', 0)
    std_l = n_std - std_w
    std_wr = bs.get('std_winrate', 0.0)

    dia_line = (
        f"• 💎 *VÙNG MUA MẠNH* (Đáy NW + SuperTrend):\n"
        f"  `{dia_w} Thắng` / `{dia_l} Thua` ({n_dia} lệnh) → *Win Rate: `{dia_wr:.1f}%`*\n"
    ) if n_dia > 0 else "• 💎 *VÙNG MUA MẠNH:* Chưa xuất hiện lệnh trong 5 năm\n"

    std_line = (
        f"• 🟢 *VÙNG MUA CHUẨN* (SuperTrend Đảo Chiều):\n"
        f"  `{std_w} Thắng` / `{std_l} Thua` ({n_std} lệnh) → *Win Rate: `{std_wr:.1f}%`*\n"
    ) if n_std > 0 else ""

    return (
        f"📊 *HIỆU QUẢ THEO VÙNG CHỈ BÁO (5 NĂM KHUNG NGÀY)*\n"
        f"{dia_line}"
        f"{std_line}"
        f"• 👉 *TỔNG CỘNG 5 NĂM:* `{tot_w} Thắng` / `{tot_l} Thua` ({tot} lệnh) → *Win Rate: `{tot_wr:.1f}%`*\n"
    )




def determine_stock_3state(res: dict):
    """
    Xác định 3 trạng thái xu hướng của cổ phiếu theo Pine Script f_trend():
    - 🟢 TĂNG: close > EMA20 AND EMA20 > EMA50 (state_d == 1)
    - 🔴 GIẢM: close < EMA20 AND EMA20 < EMA50 (state_d == -1)
    - ⚪ NGANG: các trường hợp còn lại (state_d == 0)
    Không dùng SuperTrend direction làm override — chỉ dùng EMA state.
    """
    state_d = res.get('state_d', 0)

    if state_d == 1:
        return "TĂNG", "🟢 TĂNG"
    elif state_d == -1:
        return "GIẢM", "🔴 GIẢM"
    else:
        return "NGANG", "⚪ NGANG"


def calc_market_relation(vni_state: str, stock_state: str, sym: str):
    """
    Xác định mối quan hệ giữa xu hướng VN-Index và Cổ phiếu:
    - ĐỒNG PHA (🟢)
    - TRUNG TÍNH (🟡)
    - NGƯỢC PHA (🔴)
    Kèm câu bình luận bối cảnh hoàn chỉnh.
    """
    if vni_state == "TĂNG":
        if stock_state == "TĂNG":
            relation = "ĐỒNG PHA"
            relation_badge = "🟢 ĐỒNG PHA"
            relation_str = "🟢 ĐỒNG PHA (THUẬN XU HƯỚNG THỊ TRƯỜNG)"
            comment = f"→ Cổ phiếu {sym} đang đồng pha tăng với VN-Index."
        elif stock_state == "GIẢM":
            relation = "NGƯỢC PHA"
            relation_badge = "🔴 NGƯỢC PHA"
            relation_str = "🔴 NGƯỢC PHA (NGƯỢC XU HƯỚNG THỊ TRƯỜNG)"
            comment = f"→ {sym} đang giảm, yếu hơn trạng thái chung của thị trường."
        else: # NGANG
            relation = "TRUNG TÍNH"
            relation_badge = "🟡 TRUNG TÍNH"
            relation_str = "🟡 TRUNG TÍNH (CHƯA ĐỒNG THUẬN)"
            comment = f"→ {sym} đang đi ngang tích lũy trong khi thị trường tăng."
    elif vni_state == "GIẢM":
        if stock_state == "GIẢM":
            relation = "ĐỒNG PHA"
            relation_badge = "🟢 ĐỒNG PHA"
            relation_str = "🟢 ĐỒNG PHA (THUẬN XU HƯỚNG THỊ TRƯỜNG)"
            comment = f"→ {sym} đang giảm cùng xu hướng thị trường chung."
        elif stock_state == "TĂNG":
            relation = "NGƯỢC PHA"
            relation_badge = "🔴 NGƯỢC PHA"
            relation_str = "🔴 NGƯỢC PHA (NGƯỢC XU HƯỚNG THỊ TRƯỜNG)"
            comment = (
                f"→ {sym} đang tăng trong khi VN-Index đang giảm.\n"
                f"→ Cần theo dõi khả năng duy trì xu hướng riêng của {sym}."
            )
        else: # NGANG
            relation = "TRUNG TÍNH"
            relation_badge = "🟡 TRUNG TÍNH"
            relation_str = "🟡 TRUNG TÍNH (CHƯA ĐỒNG THUẬN)"
            comment = f"→ {sym} đang giữ nền đi ngang trong khi thị trường giảm."
    else: # VN-Index NGANG
        if stock_state == "NGANG":
            relation = "TRUNG TÍNH"
            relation_badge = "⚪ CẢ HAI ĐANG NGANG"
            relation_str = "⚪ CẢ HAI ĐANG NGANG"
            comment = f"→ Cả thị trường chung và {sym} đều đang trong vùng tích lũy đi ngang."
        else:
            relation = "TRUNG TÍNH"
            relation_badge = "🟡 TRUNG TÍNH"
            relation_str = "🟡 THỊ TRƯỜNG TRUNG TÍNH"
            comment = f"→ VN-Index đang đi ngang, {sym} đang vận động theo xu hướng riêng ({stock_state})."

    return relation, relation_badge, relation_str, comment


def get_context_history_str(bs: dict, vni_state: str) -> str:
    """Format khối thống kê lịch sử trong cùng bối cảnh thị trường."""
    if not bs or bs.get('total_buys', 0) <= 0:
        return ""
    if vni_state == "GIẢM":
        v_cnt = bs.get('vni_dn_cnt', 0)
        v_win = bs.get('vni_dn_wins', 0)
        v_wr  = bs.get('vni_dn_winrate', 0.0)
        hist_label = "VN-INDEX ĐANG GIẢM"
    elif vni_state == "TĂNG":
        v_cnt = bs.get('vni_up_cnt', 0)
        v_win = bs.get('vni_up_wins', 0)
        v_wr  = bs.get('vni_up_winrate', 0.0)
        hist_label = "VN-INDEX ĐANG TĂNG"
    else:
        v_cnt = bs.get('total_buys', 0)
        v_win = bs.get('tot_wins', 0)
        v_wr  = bs.get('tot_winrate', 0.0)
        hist_label = "VN-INDEX ĐI NGANG"

    confidence = _confidence_label(v_cnt)

    if v_cnt == 0:
        return (
            f"📊 *LỊCH SỬ 5 NĂM CÙNG BỐI CẢNH ({hist_label})*\n"
            f"• ⚪ *Chưa có mẫu lệnh* trong bối cảnh này\n\n"
        )
    return (
        f"📊 *LỊCH SỬ 5 NĂM CÙNG BỐI CẢNH ({hist_label})*\n"
        f"• Số lệnh đã kiểm nghiệm: `{v_cnt}` lệnh\n"
        f"• Kết quả: *`{v_win} Thắng`* / *`{v_cnt - v_win} Thua`*\n"
        f"• Tỷ lệ thắng (Win Rate): *`{v_wr:.1f}%`*\n"
        f"• Mức độ tin cậy mẫu: {confidence}\n\n"
    )


def fmt_buy_alert(res: dict) -> str:
    """
    Format thẻ cảnh báo điểm mua gửi tự động tới Telegram khi kích hoạt trong giờ giao dịch.
    Siêu đẹp, ngắn gọn, làm nổi bật mục đích chính: Giá vào, Cắt lỗ, Chốt lời, Tỷ trọng.
    """
    sym        = res['symbol']
    ex         = res['exchange']
    comp       = get_company_info(sym)
    comp_name  = comp.get('name') or comp.get('short_name') or ''
    title_sym  = f"*{sym} — {comp_name}* (`{ex}`)" if comp_name else f"*{sym}* (`{ex}`)"

    price      = res['price_vnd']
    cur_p      = res.get('price', 0.0)
    chg        = res.get('change_pct', 0.0)
    chg_str    = _pct(chg)
    chg_icon   = "🟢" if chg >= 0 else "🔴"
    is_diamond = res.get('buy_diamond', False)
    vr         = res.get('vol_ratio', 0.0)
    t          = res.get('updated_time', '')

    # Luôn tính toán SL và TP chuẩn vị thế MUA (SL dưới giá vào, TP trên giá vào)
    cur_atr    = res.get('atr', 0.0)
    risk_val   = cur_atr * 1.5 if cur_atr > 0 else cur_p * 0.05
    sl_calc    = cur_p - risk_val
    tp1_calc   = cur_p + risk_val * config.DTPRO_RR1
    tp2_calc   = cur_p + risk_val * config.DTPRO_RR2

    sl_vnd     = format_vnd(sl_calc)
    sl_pct     = _pct((sl_calc - cur_p) / cur_p * 100.0) if cur_p > 0 else "0.0%"
    tp1_vnd    = format_vnd(tp1_calc)
    tp1_pct    = _pct((tp1_calc - cur_p) / cur_p * 100.0) if cur_p > 0 else "0.0%"
    tp2_vnd    = format_vnd(tp2_calc)
    tp2_pct    = _pct((tp2_calc - cur_p) / cur_p * 100.0) if cur_p > 0 else "0.0%"

    # Bối cảnh thị trường
    vni_info      = res.get('vni', {})
    vni_state     = vni_info.get('state', 'NGANG')
    vni_state_str = vni_info.get('state_str', '⚪ NGANG')
    vni_p         = vni_info.get('price', 0.0)
    vni_c         = vni_info.get('chg_pct', 0.0)
    vni_p_str     = f"{vni_p:,.2f} điểm".replace(",", ".") if vni_p > 0 else ""
    vni_detail    = f"({vni_p_str} • {_pct(vni_c)})" if vni_p > 0 else ""

    stock_state, _ = determine_stock_3state(res)
    relation, relation_badge, _, relation_cmt = calc_market_relation(vni_state, stock_state, sym)

    if is_diamond:
        badge_header = f"🚨 *CẢNH BÁO: KÍCH HOẠT ĐIỂM MUA MẠNH* 💎\n📈 {title_sym}"
        signal_note  = "✨ *Hợp lưu tối ưu:* Đáy Nadaraya-Watson + SuperTrend Đảo chiều TĂNG 🟢"
    else:
        badge_header = f"🚨 *CẢNH BÁO: KÍCH HOẠT ĐIỂM MUA CHUẨN* 🟢\n📈 {title_sym}"
        signal_note  = "📈 *Tín hiệu:* SuperTrend Keltner chính thức Đảo chiều TĂNG 🟢"

    bs = res.get('buy_stats', {})
    stats_block = fmt_stats_block(sym, bs)

    msg = (
        f"{badge_header}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Giá kích hoạt:* `{price}` ({chg_icon} `{chg_str}`) | 📊 *Vol:* `{vr:.1f}x` MA20\n"
        f"⏰ *Thời gian:* _{t} (Thời gian thực)_\n\n"

        f"{signal_note}\n"
        f"🌐 *Thị trường:* VN-Index {vni_state_str} {vni_detail}\n"
        f"🔎 *Tương quan:* *{relation_badge}* — {relation_cmt}\n\n"

        f"🎯 *KẾ HOẠCH GIẢI NGÂN (R:R CHUẨN)*\n"
        f"• 🎯 Điểm mua (Entry): `{price}`\n"
        f"• 🛑 Cắt lỗ (SL):      `{sl_vnd}` ({sl_pct})\n"
        f"• 🏆 Chốt lời 1 (TP1): `{tp1_vnd}` ({tp1_pct}) — _(1.0R - Dời SL hòa vốn)_\n"
        f"• 🚀 Chốt lời 2 (TP2): `{tp2_vnd}` ({tp2_pct}) — _(2.0R - Mục tiêu chính)_\n\n"

        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{stats_block}\n"
        f"💡 _Khuyến nghị: Phân bổ tối đa 2% NAV tài khoản cho vị thế này!_"
    )
    return msg


def fmt_detail(res: dict) -> str:
    """
    Format tin nhắn tra cứu chi tiết 1 mã, siêu đẹp, ngắn gọn, dễ hiểu,
    phân định rõ ràng 3 trạng thái:
      1. Có điểm MUA hôm nay -> Kế hoạch giải ngân ngay
      2. Đang trong sóng TĂNG -> Đang nắm giữ, không mua đuổi
      3. Đang trong nhịp GIẢM / CHƯA CÓ ĐIỂM MUA -> Đứng ngoài quan sát
    Tránh tuyệt đối việc hiển thị các lệnh bán/mua cũ từ hàng chục phiên trước gây hiểu lầm.
    """
    sym       = res['symbol']
    ex        = res['exchange']
    comp      = get_company_info(sym)
    comp_name = comp.get('name') or comp.get('short_name') or ''
    title_sym = f"*{sym} — {comp_name}* (`{ex}`)" if comp_name else f"*{sym}* (`{ex}`)"

    price     = res['price_vnd']
    cur_p     = res.get('price', 0.0)
    chg       = res.get('change_pct', 0.0)
    chg_i     = "🟢" if chg >= 0 else "🔴"
    chg_str   = _pct(chg)
    vr        = res.get('vol_ratio', 0.0)
    t         = res.get('updated_time', '')
    
    # Tính SL/TP chuẩn cho vị thế Mua
    cur_atr   = res.get('atr', 0.0)
    risk_val  = cur_atr * 1.5 if cur_atr > 0 else cur_p * 0.05
    sl_calc   = cur_p - risk_val
    tp1_calc  = cur_p + risk_val * config.DTPRO_RR1
    tp2_calc  = cur_p + risk_val * config.DTPRO_RR2

    sl_vnd    = format_vnd(sl_calc)
    sl_pct    = _pct((sl_calc - cur_p) / cur_p * 100.0) if cur_p > 0 else "0.0%"
    tp1_vnd   = format_vnd(tp1_calc)
    tp1_pct   = _pct((tp1_calc - cur_p) / cur_p * 100.0) if cur_p > 0 else "0.0%"
    tp2_vnd   = format_vnd(tp2_calc)
    tp2_pct   = _pct((tp2_calc - cur_p) / cur_p * 100.0) if cur_p > 0 else "0.0%"

    # Bối cảnh VN-Index
    vni_info      = res.get('vni', {})
    vni_state     = vni_info.get('state', 'NGANG')
    vni_state_str = vni_info.get('state_str', '⚪ NGANG')
    vni_p         = vni_info.get('price', 0.0)
    vni_c         = vni_info.get('chg_pct', 0.0)
    vni_p_str     = f"{vni_p:,.2f} điểm".replace(",", ".") if vni_p > 0 else ""
    vni_detail    = f"({vni_p_str} • {_pct(vni_c)})" if vni_p > 0 else ""

    stock_state, _ = determine_stock_3state(res)
    relation, relation_badge, _, relation_cmt = calc_market_relation(vni_state, stock_state, sym)

    # Thống kê lịch sử 5 năm
    bs = res.get('buy_stats', {})
    stats_sec = fmt_stats_block(sym, bs)

    is_buy_today = res.get('buy_diamond') or res.get('buy_standard')
    is_diamond   = res.get('buy_diamond', False)
    active_pos   = res.get('active_pos', 0)
    bars_ago     = res.get('bars_since_trigger', 0)
    entry_p      = res.get('entry_price_vnd', price)
    entry_val    = res.get('entry_p', cur_p)

    # Khối trạng thái và hành động
    if is_buy_today:
        if is_diamond:
            status_header = "💎 *KÍCH HOẠT ĐIỂM MUA MẠNH HÔM NAY!*"
            status_desc   = "✨ *Hợp lưu tối ưu:* Đáy Nadaraya-Watson + SuperTrend Đảo chiều TĂNG 🟢\n👉 *Hành động:* **GIẢI NGÂN MUA** (Tỷ trọng tối đa 2% NAV tài khoản)"
        else:
            status_header = "🟢 *KÍCH HOẠT ĐIỂM MUA CHUẨN HÔM NAY!*"
            status_desc   = "📈 *Tín hiệu:* SuperTrend Keltner chính thức Đảo chiều TĂNG 🟢\n👉 *Hành động:* **GIẢI NGÂN MUA** (Tỷ trọng tối đa 2% NAV tài khoản)"

        plan_block = (
            f"🎯 *KẾ HOẠCH GIAO DỊCH (R:R CHUẨN)*\n"
            f"• 🎯 Điểm mua (Entry): `{price}`\n"
            f"• 🛑 Cắt lỗ (SL):      `{sl_vnd}` ({sl_pct})\n"
            f"• 🏆 Mục tiêu 1 (TP1): `{tp1_vnd}` ({tp1_pct}) — _(Dời SL hòa vốn)_\n"
            f"• 🚀 Mục tiêu 2 (TP2): `{tp2_vnd}` ({tp2_pct}) — _(Chốt lời chính)_\n"
        )
    elif active_pos == 1:
        pnl = (cur_p - entry_val) / entry_val * 100.0 if entry_val > 0 else 0.0
        pnl_str = _pct(pnl)
        pnl_icon = "🟢" if pnl >= 0 else "🔴"
        
        status_header = f"🟢 *ĐANG NẮM GIỮ (Vị thế MUA từ {bars_ago} phiên trước)*"
        status_desc   = (
            f"• Giá mua ban đầu: `{entry_p}`\n"
            f"• Lợi nhuận tạm tính: {pnl_icon} *`{pnl_str}`*\n"
            f"👉 *Hành động:* **TIẾP TỤC NẮM GIỮ** — Tuyệt đối không mua đuổi thêm!"
        )
        plan_block = (
            f"🎯 *CÁC MỐC QUẢN TRỊ VỊ THẾ*\n"
            f"• 🛑 Cắt lỗ bảo toàn vốn (SL): `{format_vnd(res.get('sl', sl_calc))}`\n"
            f"• 🏆 Mục tiêu chốt lời 1 (TP1): `{format_vnd(res.get('tp1', tp1_calc))}`\n"
            f"• 🚀 Mục tiêu chốt lời 2 (TP2): `{format_vnd(res.get('tp2', tp2_calc))}`\n"
        )
    else:
        # Đang trong nhịp giảm hoặc đi ngang không có điểm mua
        if stock_state == "GIẢM":
            status_header = "🔴 *ĐANG TRONG XU HƯỚNG GIẢM — CHƯA CÓ ĐIỂM MUA*"
            status_desc   = "👉 *Hành động:* **ĐỨNG NGOÀI QUAN SÁT** — Tuyệt đối không bắt đáy!\n• Cổ phiếu đang chịu áp lực điều chỉnh, kiên nhẫn chờ dòng tiền đảo chiều."
        else:
            status_header = "⚪ *ĐANG TÍCH LŨY ĐI NGANG — TIẾP TỤC QUAN SÁT*"
            status_desc   = "👉 *Hành động:* **ĐỨNG NGOÀI QUAN SÁT**\n• Cổ phiếu đang trong vùng tích lũy, chờ đợi phiên bùng nổ vượt cản."
        plan_block = ""

    plan_divider = "━━━━━━━━━━━━━━━━━━━━\n" if plan_block else ""

    msg = (
        f"📊 {title_sym}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Thị giá:* `{price}` ({chg_i} `{chg_str}`) | 📊 *Vol:* `{vr:.1f}x` MA20\n"
        f"⏰ *Cập nhật:* _{t}_\n\n"

        f"📌 *TRẠNG THÁI HIỆN TẠI*\n"
        f"{status_header}\n"
        f"{status_desc}\n\n"

        f"{plan_block}"
        f"{plan_divider}"

        f"🌐 *BỐI CẢNH THỊ TRƯỜNG (VN-INDEX)*\n"
        f"• VN-Index: {vni_state_str} {vni_detail}\n"
        f"• Tương quan: *{relation_badge}* — {relation_cmt}\n\n"

        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{stats_sec}\n"
        f"💡 _Gõ tên mã bất kỳ (VD: HPG, SSI, FPT, VCB) để tra cứu nhanh!_"
    )
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
            last_scan = time.time()

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
