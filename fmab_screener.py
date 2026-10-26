# -*- coding: utf-8 -*-
"""
fmab_screener.py — Quét thị trường & Tra cứu cổ phiếu theo chỉ báo FMAB
[blackcat] L1 Fibonacci MA Band (FMAB Pro)
"""

import concurrent.futures
import time
import threading
from datetime import datetime
from typing import List, Optional, Dict

import numpy as np
import pandas as pd

import config
from screener import (
    get_exchange_symbols_snapshot,
    get_live_stock_quote,
    get_ticker_history,
    normalize_price_k,
    format_vnd,
    is_trading_hour,
    get_elapsed_trading_minutes,
)
import fmab_indicators


def _parse_item(item: dict):
    raw_price = (item.get("matchedPrice") or item.get("lastPrice") or
                 item.get("expectedMatchedPrice") or item.get("close", 0))
    raw_vol   = (item.get("nmTotalTradedQty") or item.get("stockVol") or
                 item.get("totalVol") or item.get("expectedMatchedVolume", 0))
    raw_high  = item.get("highest") or item.get("highestPrice") or item.get("high") or 0
    raw_low   = item.get("lowest")  or item.get("lowestPrice")  or item.get("low")  or 0
    chg       = float(item.get("priceChangePercent") or item.get("changePercent") or 0.0)
    raw_val   = float(item.get("totalVal") or item.get("totalValue") or 0)
    price     = normalize_price_k(raw_price)
    vol       = float(raw_vol) if raw_vol else 0.0
    high      = normalize_price_k(raw_high) or price
    low       = normalize_price_k(raw_low)  or price
    return price, vol, high, low, chg, raw_val


def analyze_single(symbol: str) -> Optional[Dict]:
    """Phân tích 1 mã cổ phiếu chi tiết theo chiến lược FMAB."""
    symbol = symbol.strip().upper()
    item = get_live_stock_quote(symbol)
    exchange = item.get("exchange_name", "HOSE")
    price, vol, high, low, chg, _ = _parse_item(item)

    df = get_ticker_history(symbol, count=None, days=config.DTPRO_HISTORY_DAYS)
    if df is None or len(df) < 50:
        return None

    # Ghép nến realtime nếu có
    if price > 0 and len(df) > 0:
        last_idx = df.index[-1]
        df.loc[last_idx, 'close'] = price
        if high > df.loc[last_idx, 'high']:
            df.loc[last_idx, 'high'] = high
        if low < df.loc[last_idx, 'low'] and low > 0:
            df.loc[last_idx, 'low'] = low
        if vol > df.loc[last_idx, 'volume']:
            df.loc[last_idx, 'volume'] = vol

    res = fmab_indicators.compute_fmab(df)
    if not res:
        return None

    res['symbol'] = symbol
    res['exchange'] = exchange
    res['updated_time'] = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
    res['price_vnd'] = format_vnd(res['price'])
    res['whale_ma_vnd'] = format_vnd(res['whale_ma'])
    res['res_ma_vnd'] = format_vnd(res['res_ma'])
    res['trendline_ma_vnd'] = format_vnd(res['trendline_ma'])
    res['entry_price_vnd'] = format_vnd(res['entry_price']) if not np.isnan(res['entry_price']) else "—"
    res['sl_vnd'] = format_vnd(res['sl_price']) if not np.isnan(res['sl_price']) else "—"
    res['tp_vnd'] = format_vnd(res['tp_price']) if not np.isnan(res['tp_price']) else "—"
    res['plan_entry_vnd'] = format_vnd(res.get('plan_entry_price', res['price']))
    res['plan_sl_vnd'] = format_vnd(res.get('plan_sl_price', res['price'] - 2.0 * res['atr']))
    res['plan_tp_vnd'] = format_vnd(res.get('plan_tp_price', res['price'] + 3.0 * res['atr']))
    res['ma_exit_vnd'] = format_vnd(res.get('ma_exit_price', res['whale_ma']))

    return res


def _analyze_one(item: dict, exchange: str) -> Optional[Dict]:
    symbol = (item.get("stockSymbol") or item.get("symbol") or "").strip().upper()
    if not symbol or len(symbol) < 2 or len(symbol) > 5 or not symbol.isalpha():
        return None

    price, vol, high, low, chg, raw_val = _parse_item(item)

    # Lọc thanh khoản tối thiểu
    elapsed = get_elapsed_trading_minutes()
    min_val = (1_000_000_000 if elapsed <= 45 else
               2_000_000_000 if elapsed <= 90 else config.MIN_TRADE_VALUE)
    if price > 0 and vol > 0:
        est = raw_val if raw_val > 0 else price * 1000.0 * vol
        if est < min_val:
            return None

    df = get_ticker_history(symbol, count=160, days=240)
    if df is None or len(df) < 50:
        return None

    if price > 0 and len(df) > 0:
        last_idx = df.index[-1]
        df.loc[last_idx, 'close'] = price
        if high > df.loc[last_idx, 'high']:
            df.loc[last_idx, 'high'] = high
        if low < df.loc[last_idx, 'low'] and low > 0:
            df.loc[last_idx, 'low'] = low
        if vol > df.loc[last_idx, 'volume']:
            df.loc[last_idx, 'volume'] = vol

    res = fmab_indicators.compute_fmab(df)
    if not res:
        return None

    res['symbol'] = symbol
    res['exchange'] = exchange
    res['updated_time'] = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
    res['price_vnd'] = format_vnd(res['price'])
    res['whale_ma_vnd'] = format_vnd(res['whale_ma'])
    res['res_ma_vnd'] = format_vnd(res['res_ma'])
    res['trendline_ma_vnd'] = format_vnd(res['trendline_ma'])
    res['entry_price_vnd'] = format_vnd(res['entry_price']) if not np.isnan(res['entry_price']) else "—"
    res['sl_vnd'] = format_vnd(res['sl_price']) if not np.isnan(res['sl_price']) else "—"
    res['tp_vnd'] = format_vnd(res['tp_price']) if not np.isnan(res['tp_price']) else "—"
    res['plan_entry_vnd'] = format_vnd(res.get('plan_entry_price', res['price']))
    res['plan_sl_vnd'] = format_vnd(res.get('plan_sl_price', res['price'] - 2.0 * res['atr']))
    res['plan_tp_vnd'] = format_vnd(res.get('plan_tp_price', res['price'] + 3.0 * res['atr']))
    res['ma_exit_vnd'] = format_vnd(res.get('ma_exit_price', res['whale_ma']))

    return res


_fmab_cache = {}
_fmab_cache_time = {}
_fmab_lock = threading.Lock()

def run_fmab_screener(buy_only: bool = True) -> List[Dict]:
    """
    Quét toàn thị trường HOSE + HNX theo bộ chỉ báo FMAB.
    - buy_only=True: Chỉ lấy mã có điểm MUA hôm nay (nến hiện tại cắt lên Whale MA).
    """
    cache_key = buy_only
    now_ts = time.time()
    with _fmab_lock:
        if cache_key in _fmab_cache and (now_ts - _fmab_cache_time.get(cache_key, 0) < 45):
            return _fmab_cache[cache_key].copy()

    elapsed = get_elapsed_trading_minutes()
    min_val = (1_000_000_000 if elapsed <= 45 else
               2_000_000_000 if elapsed <= 90 else config.MIN_TRADE_VALUE)

    all_items = []
    for ex in config.EXCHANGES:
        snap = get_exchange_symbols_snapshot(ex)
        for item in snap:
            symbol = (item.get("stockSymbol") or item.get("symbol") or "").strip().upper()
            if not symbol or len(symbol) < 2 or len(symbol) > 5 or not symbol.isalpha():
                continue
            price, vol, high, low, chg, raw_val = _parse_item(item)
            if price > 0 and vol > 0:
                est = raw_val if raw_val > 0 else price * 1000.0 * vol
                if est < min_val:
                    continue
            all_items.append((item, ex.upper()))

    results = []
    workers = config.MAX_WORKERS
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_analyze_one, item, ex): (item, ex)
                   for item, ex in all_items}
        for future in concurrent.futures.as_completed(futures):
            try:
                res = future.result()
                if res is None:
                    continue
                if buy_only and not res.get('has_buy_signal'):
                    continue
                results.append(res)
            except Exception:
                pass

    # Sắp xếp: Hợp lưu cao nhất (3 sao -> 2 sao) lên đầu, tiếp đến vol_ratio
    results.sort(key=lambda x: (
        -int(x.get('confluence_score', 0)),
        -float(x.get('vol_ratio', 0.0)),
        -float(x.get('change_pct', 0.0)),
    ))

    with _fmab_lock:
        _fmab_cache[cache_key] = results
        _fmab_cache_time[cache_key] = time.time()

    return results


# ─────────────────────────────────────────────────────────────
# ĐỊNH DẠNG TIN NHẮN TELEGRAM (TELEGRAM MESSAGE FORMATTERS)
# ─────────────────────────────────────────────────────────────

def fmt_fmab_detail(res: dict) -> str:
    """Định dạng phân tích chi tiết FMAB cho lệnh tra cứu /fmab <MÃ>."""
    sym = res['symbol']
    ex = res['exchange']
    price_vnd = res['price_vnd']
    chg = res['change_pct']
    chg_icon = "🟢" if chg > 0 else ("🔴" if chg < 0 else "⚪")
    vol_ratio = res['vol_ratio']
    vol_str = f"{vol_ratio:.1f}x MA20" if vol_ratio >= 1.0 else f"{vol_ratio:.1f}x MA20"

    w_vnd = res['whale_ma_vnd']
    r_vnd = res['res_ma_vnd']
    t_vnd = res['trendline_ma_vnd']

    band_name = res['band_name']
    trend_name = res['trend_name']
    conf_tag = res['confluence_tag']
    action_title = res['action_title']
    action_detail = res['action_detail']

    pos_state = res['pos_state']
    has_buy_signal = res.get('has_buy_signal', False)
    profit_pct = res.get('profit_pct', 0.0)

    # ── Kế hoạch giao dịch theo L1 Fibonacci MA Band (TradingView: OZhERgT3) ──
    atr_val = res.get('atr', 0.0)
    plan_entry_vnd = res.get('plan_entry_vnd', price_vnd)
    plan_sl_vnd = res.get('plan_sl_vnd', '—')
    plan_tp_vnd = res.get('plan_tp_vnd', '—')
    plan_sl_pct = res.get('plan_sl_pct', -4.0)
    plan_tp_pct = res.get('plan_tp_pct', 6.0)

    lines = [
        f"📊 *PHÂN TÍCH FIBONACCI MA BAND (FMAB)* 📊",
        f"*{sym}* ({ex}) — {price_vnd} ({chg_icon} {chg:+.2f}%)",
        f"⏰ {res['updated_time']} | KL: `{vol_str}`",
        f"────────────────────────",
        f"🎯 *HÀNH ĐỘNG:* {action_title}",
        f"💬 {action_detail}",
        f"📌 *Hợp Lưu Xu Hướng:* {conf_tag}",
        f"────────────────────────",
        f"🌊 *HỆ THỐNG ĐƯỜNG TRUNG BÌNH:*",
        f"• *Whale MA (EMA 13):* `{w_vnd}`",
        f"• *Resistance MA (EMA 144):* `{r_vnd}`",
        f"• *Trendline MA (EMA 50):* `{t_vnd}`",
        f"• *Dải MA Band:* {band_name}",
        f"• *Động lượng:* {trend_name}",
        f"────────────────────────",
    ]

    if pos_state == 1:
        lines += [
            f"🛡️ *KẾ HOẠCH VỊ THẾ ĐANG NẮM GIỮ (LONG):*",
            f"• Giá vào lệnh (Entry): `{res['entry_price_vnd']}` (Hiệu suất: `{profit_pct:+.2f}%`)",
            f"• Chốt lời mục tiêu (+3.0x ATR): `{res['tp_vnd']}` ({res['tp_pct']:+.1f}%)",
            f"• Cắt lỗ cố định (-2.0x ATR): `{res['sl_vnd']}` ({res['sl_pct']:+.1f}%)",
            f"• Điểm thoát sớm (MA Exit): Đóng nến ngày gãy Whale MA `{w_vnd}`",
            f"• Tỷ lệ Lợi nhuận / Rủi ro: `1 : 1.5` (Kỳ vọng +3 ATR / Rủi ro -2 ATR)",
        ]
    elif has_buy_signal:
        lines += [
            f"🎯 *KẾ HOẠCH VÀO LỆNH MUA MỚI HÔM NAY:*",
            f"• Giá kích hoạt Mua (Entry): `{price_vnd}`",
            f"• Chốt lời mục tiêu (+3.0x ATR): `{plan_tp_vnd}` ({plan_tp_pct:+.1f}%)",
            f"• Cắt lỗ cố định (-2.0x ATR): `{plan_sl_vnd}` ({plan_sl_pct:+.1f}%)",
            f"• Điểm thoát sớm (MA Exit): Đóng nến ngày gãy Whale MA `{w_vnd}`",
            f"• Tỷ lệ Lợi nhuận / Rủi ro: `1 : 1.5` (Kỳ vọng +3 ATR / Rủi ro -2 ATR)",
        ]
    else:
        lines += [
            f"📋 *KẾ HOẠCH GIAO DỊCH DỰ KIẾN (CHỜ MUA):*",
            f"• Điều kiện kích hoạt: Giá cắt lên & đóng nến trên Whale MA `{w_vnd}`",
            f"• Giá vào tham chiếu (Entry): `{plan_entry_vnd}`",
            f"• Chốt lời mục tiêu (+3.0x ATR): `{plan_tp_vnd}` ({plan_tp_pct:+.1f}%)",
            f"• Cắt lỗ phòng thủ (-2.0x ATR): `{plan_sl_vnd}` ({plan_sl_pct:+.1f}%)",
            f"• Điểm thoát bảo toàn vốn (MA Exit): Bán nếu đóng nến gãy Whale MA",
            f"• Tỷ lệ Lợi nhuận / Rủi ro: `1 : 1.5` (Kỳ vọng +3 ATR / Rủi ro -2 ATR)",
        ]

    lines += [
        f"────────────────────────",
        f"💡 _Chuẩn tác giả blackcat1402 (TradingView: OZhERgT3): Chốt lời TP = Entry + 3x ATR, Cắt lỗ SL = Entry - 2x ATR. Thoát lệnh khi gãy Whale MA._"
    ]
    return "\n".join(lines)


def fmt_fmab_buy_alert(res: dict) -> str:
    """Định dạng cảnh báo điểm MUA FMAB bắn vào Telegram."""
    sym = res['symbol']
    ex = res['exchange']
    price_vnd = res['price_vnd']
    chg = res['change_pct']
    chg_icon = "🟢" if chg > 0 else "⚪"
    vol_ratio = res['vol_ratio']

    plan_sl_vnd = res.get('plan_sl_vnd', res.get('sl_vnd', '—'))
    plan_tp_vnd = res.get('plan_tp_vnd', res.get('tp_vnd', '—'))
    plan_sl_pct = res.get('plan_sl_pct', res.get('sl_pct', 0.0))
    plan_tp_pct = res.get('plan_tp_pct', res.get('tp_pct', 0.0))

    lines = [
        f"⚡ *[CẢNH BÁO FMAB] KÍCH HOẠT ĐIỂM MUA* ⚡",
        f"Mã: *{sym}* ({ex}) | Giá: *{price_vnd}* ({chg_icon} {chg:+.2f}%)",
        f"⏰ {res['updated_time']} | KL: `{vol_ratio:.1f}x MA20`",
        f"────────────────────────",
        f"✨ *Bứt Phá:* Giá vừa cắt lên trên Whale MA ({res['whale_ma_vnd']})",
        f"🎯 *Đánh giá hợp lưu:* {res['confluence_tag']}",
        f"🌊 *Dải MA Band:* {res['band_name']}",
        f"📈 *Động lượng:* {res['trend_name']}",
        f"────────────────────────",
        f"🎯 *KẾ HOẠCH GIAO DỊCH CHUẨN (FMAB OZhERgT3):*",
        f"• Vùng mua Entry: `{price_vnd}`",
        f"• Chốt lời mục tiêu TP (+3.0x ATR): `{plan_tp_vnd}` ({plan_tp_pct:+.1f}%)",
        f"• Cắt lỗ cố định SL (-2.0x ATR): `{plan_sl_vnd}` ({plan_sl_pct:+.1f}%)",
        f"• Điểm thoát sớm (MA Exit): Đóng nến ngày thủng Whale MA `{res['whale_ma_vnd']}`",
        f"• Tỷ lệ Lợi nhuận / Rủi ro: `1 : 1.5` (Kỳ vọng +3 ATR / Rủi ro -2 ATR)",
        f"────────────────────────",
        f"👉 _Gõ `/{sym.lower()}` để xem phân tích chi tiết!_"
    ]
    return "\n".join(lines)


def fmt_fmab_scan_summary(buy_signals: List[Dict], time_tag: str = "") -> str:
    """Tóm tắt kết quả quét FMAB toàn thị trường."""
    if not buy_signals:
        return (
            f"🔍 *KẾT QUẢ QUÉT FMAB PRO* {time_tag}\n"
            f"────────────────────────\n"
            f"Hiện tại không có mã nào vừa kích hoạt điểm MUA nến hôm nay.\n"
            f"Thị trường đang trong nhịp tích lũy hoặc chờ xác nhận bứt phá Whale MA.\n"
            f"👉 _Bạn có thể gõ trực tiếp tên mã (VD: `HPG`, `SSI`) để kiểm tra vị thế!_"
        )

    lines = [
        f"🚀 *DANH SÁCH ĐIỂM MUA FMAB HÔM NAY* {time_tag} 🚀",
        f"Hệ thống phát hiện {len(buy_signals)} mã bứt phá Whale MA (EMA 13):\n"
    ]

    for i, s in enumerate(buy_signals[:15], 1):
        sym = s['symbol']
        p = s['price_vnd']
        chg = s['change_pct']
        chg_icon = "🟢" if chg > 0 else "⚪"
        vol = s['vol_ratio']
        conf = "⭐" * s.get('confluence_score', 1)
        lines.append(f"{i}. *{sym}* ({s['exchange']}): {p} ({chg_icon}{chg:+.1f}%) | KL: `{vol:.1f}x` | {conf}")
        lines.append(f"   ↳ Entry: `{p}` | SL: `{s['sl_vnd']}` | TP: `{s['tp_vnd']}`\n")

    if len(buy_signals) > 15:
        lines.append(f"_...và còn {len(buy_signals) - 15} mã khác đạt tiêu chuẩn._")

    lines.append("────────────────────────")
    lines.append("👉 _Gõ `/fmab <MÃ>` (VD: `/fmab SSI`) để xem chi tiết từng mã!_")
    return "\n".join(lines)
