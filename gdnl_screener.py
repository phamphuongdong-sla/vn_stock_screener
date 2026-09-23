# -*- coding: utf-8 -*-
"""
gdnl_screener.py — Quét toàn sàn HOSE + HNX theo chỉ báo GDNL.
Tái sử dụng hàm fetch data từ screener.py (get_exchange_symbols_snapshot,
get_live_stock_quote, get_ticker_history, normalize_price_k, format_vnd).
"""

import concurrent.futures
import time
from datetime import datetime
from typing import List, Optional, Dict

import pandas as pd
import numpy as np

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
from gdnl_indicators import analyze_gdnl


def _parse_live_item(item: dict):
    """Trích xuất giá, khối lượng, % thay đổi từ dict bảng giá SSI."""
    raw_price = (
        item.get("matchedPrice") or
        item.get("lastPrice") or
        item.get("expectedMatchedPrice") or
        item.get("close", 0)
    )
    raw_vol = (
        item.get("nmTotalTradedQty") or
        item.get("stockVol") or
        item.get("totalVol") or
        item.get("expectedMatchedVolume", 0)
    )
    change_pct = float(
        item.get("priceChangePercent") or
        item.get("changePercent") or
        item.get("matchedPricePercent") or 0.0
    )
    raw_val = float(item.get("totalVal") or item.get("totalValue") or 0)
    price = normalize_price_k(raw_price)
    vol   = float(raw_vol) if raw_vol else 0.0
    return price, vol, change_pct, raw_val


def analyze_one(item: dict, exchange: str) -> Optional[Dict]:
    """Phân tích 1 mã cổ phiếu với bộ chỉ báo GDNL."""
    symbol = (
        item.get("stockSymbol") or
        item.get("ssi_symbol") or
        item.get("symbol") or ""
    ).strip().upper()

    if not symbol or len(symbol) < 2 or len(symbol) > 5 or not symbol.isalpha():
        return None

    price, vol, change_pct, raw_val = _parse_live_item(item)

    # Lọc thanh khoản tối thiểu
    elapsed = get_elapsed_trading_minutes()
    min_val = 1_000_000_000 if elapsed <= 45 else (2_000_000_000 if elapsed <= 90 else config.MIN_TRADE_VALUE)

    if price > 0 and vol > 0:
        est_val = raw_val if raw_val > 0 else price * 1000.0 * vol
        if est_val < min_val:
            return None

    # Lấy lịch sử nến ngày
    df = get_ticker_history(symbol, count=150)
    if df is None or len(df) < 60:
        return None

    result = analyze_gdnl(
        df,
        symbol=symbol,
        exchange=exchange,
        live_price=price,
        live_vol=vol,
        change_pct=change_pct,
        st_length=config.GDNL_ST_LENGTH,
        atr_length=config.GDNL_ATR_LENGTH,
        atr_mult=config.GDNL_ATR_MULT,
        ema_fast_len=config.GDNL_EMA_FAST,
        ema_slow_len=config.GDNL_EMA_SLOW,
        adx_len=config.GDNL_ADX_LEN,
        adx_min=config.GDNL_ADX_MIN,
        vol_len=config.GDNL_VOL_LEN,
        pivot_len=config.GDNL_PIVOT_LEN,
        tp1_rr=config.GDNL_TP1_RR,
        tp2_rr=config.GDNL_TP2_RR,
        min_score=config.GDNL_MIN_SCORE,
    )
    return result


def analyze_single_symbol(symbol: str) -> Optional[Dict]:
    """
    Phân tích chi tiết 1 mã đơn lẻ (cho tra cứu Telegram).
    Luôn trả về kết quả kể cả khi không có tín hiệu.
    """
    symbol = symbol.strip().upper()
    item   = get_live_stock_quote(symbol)
    exchange = item.get("exchange_name", "HOSE")

    price, vol, change_pct, raw_val = _parse_live_item(item)

    df = get_ticker_history(symbol, count=150)
    if df is None or len(df) < 60:
        return None

    result = analyze_gdnl(
        df,
        symbol=symbol,
        exchange=exchange,
        live_price=price,
        live_vol=vol,
        change_pct=change_pct,
        st_length=config.GDNL_ST_LENGTH,
        atr_length=config.GDNL_ATR_LENGTH,
        atr_mult=config.GDNL_ATR_MULT,
        ema_fast_len=config.GDNL_EMA_FAST,
        ema_slow_len=config.GDNL_EMA_SLOW,
        adx_len=config.GDNL_ADX_LEN,
        adx_min=config.GDNL_ADX_MIN,
        vol_len=config.GDNL_VOL_LEN,
        pivot_len=config.GDNL_PIVOT_LEN,
        tp1_rr=config.GDNL_TP1_RR,
        tp2_rr=config.GDNL_TP2_RR,
        min_score=config.GDNL_MIN_SCORE,
    )
    return result


def run_gdnl_screener(signal_only: bool = True) -> List[Dict]:
    """
    Quét toàn bộ thị trường HOSE + HNX.
    signal_only=True  → chỉ trả về mã có tín hiệu MUA hoặc BÁN
    signal_only=False → trả về tất cả
    Kết quả sắp xếp theo trend_score DESC.
    """
    all_items = []
    for ex in config.EXCHANGES:
        snapshot = get_exchange_symbols_snapshot(ex)
        for item in snapshot:
            item['_exchange'] = ex.upper()
        all_items.extend([(item, ex.upper()) for item in snapshot])

    print(f"[GDNL] Nhận được {len(all_items)} mã từ {config.EXCHANGES}. Đang phân tích đa luồng...")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
        futures = {
            executor.submit(analyze_one, item, ex): (item, ex)
            for item, ex in all_items
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                res = future.result()
                if res is None:
                    continue
                if signal_only and not res['buy_signal'] and not res['sell_signal']:
                    continue
                results.append(res)
            except Exception:
                pass

    results.sort(key=lambda x: x['trend_score'], reverse=True)
    print(f"[GDNL] Hoàn tất — {len(results)} mã{'có tín hiệu' if signal_only else ''} tìm thấy.")
    return results
