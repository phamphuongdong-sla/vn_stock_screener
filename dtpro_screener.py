# -*- coding: utf-8 -*-
"""
dtpro_screener.py — Quét toàn sàn HOSE+HNX theo chỉ báo DÒNG TIỀN PRO.
"""

import concurrent.futures
import time
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
from dtpro_indicators import analyze_dtpro


def _parse_item(item: dict):
    raw_price = (item.get("matchedPrice") or item.get("lastPrice") or
                 item.get("expectedMatchedPrice") or item.get("close", 0))
    raw_vol   = (item.get("nmTotalTradedQty") or item.get("stockVol") or
                 item.get("totalVol") or item.get("expectedMatchedVolume", 0))
    raw_high  = item.get("highest") or item.get("highestPrice") or item.get("high") or 0
    raw_low   = item.get("lowest")  or item.get("lowestPrice")  or item.get("low")  or 0
    chg = float(item.get("priceChangePercent") or item.get("changePercent") or 0.0)
    raw_val = float(item.get("totalVal") or item.get("totalValue") or 0)
    price = normalize_price_k(raw_price)
    vol   = float(raw_vol) if raw_vol else 0.0
    high  = normalize_price_k(raw_high) or price
    low   = normalize_price_k(raw_low)  or price
    return price, vol, high, low, chg, raw_val


def analyze_one(item: dict, exchange: str) -> Optional[Dict]:
    """Phân tích 1 mã cổ phiếu với bộ chỉ báo DTPro."""
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

    # Fetch đủ lịch sử cho NW kernel
    df = get_ticker_history(symbol, count=None, days=config.DTPRO_HISTORY_DAYS)
    if df is None or len(df) < 60:
        return None

    res = analyze_dtpro(
        df, symbol=symbol, exchange=exchange,
        live_price=price, live_high=high, live_low=low,
        live_vol=vol, change_pct=chg,
        st_len=config.DTPRO_ST_LEN, atr_len=config.DTPRO_ATR_LEN,
        st_mult=config.DTPRO_ST_MULT,
        ema_fast=config.DTPRO_EMA_FAST, ema_slow=config.DTPRO_EMA_SLOW,
        nw_h=config.DTPRO_NW_H, nw_mult=config.DTPRO_NW_MULT,
        nw_win=config.DTPRO_NW_WIN,
        cua_so_lookback=config.DTPRO_LOOKBACK,
        rr1=config.DTPRO_RR1, rr2=config.DTPRO_RR2,
    )
    if res:
        res['vni'] = get_vnindex_status()
    return res


_vni_cache = None
_vni_cache_time = 0

def get_vnindex_status() -> dict:
    """Lấy trạng thái xu hướng của VN-INDEX thời gian thực (kèm cache 5 phút)."""
    global _vni_cache, _vni_cache_time
    now = time.time()
    if _vni_cache is not None and (now - _vni_cache_time < 300):
        return _vni_cache

    try:
        from screener import get_session
        s = get_session()
        now_ts = int(now)
        from_ts = now_ts - 200 * 86400
        u = f"https://services.entrade.com.vn/chart-api/v2/ohlcs/index?from={from_ts}&to={now_ts}&symbol=VNINDEX&resolution=1D"
        r = s.get(u, timeout=(2.0, 4.0))
        if r.status_code == 200:
            d = r.json()
            c_series = pd.Series(d['c'])
            ma20 = float(c_series.rolling(20).mean().iloc[-1])
            cur_p = float(c_series.iloc[-1])
            prev_p = float(c_series.iloc[-2]) if len(c_series) > 1 else cur_p
            chg = (cur_p - prev_p) / prev_p * 100
            is_up = cur_p >= ma20
            
            _vni_cache = {
                'price': cur_p,
                'chg_pct': chg,
                'ma20': ma20,
                'is_uptrend': is_up,
                'label': "TĂNG 🟢 (Thuận xu hướng)" if is_up else "GIẢM 🔴 (Ngược xu hướng)",
                'status_str': "TĂNG 🟢" if is_up else "GIẢM 🔴",
            }
            _vni_cache_time = now
            return _vni_cache
    except Exception:
        pass

    if _vni_cache is not None:
        return _vni_cache

    return {
        'price': 0.0, 'chg_pct': 0.0, 'ma20': 0.0, 'is_uptrend': True,
        'label': "TĂNG 🟢 (Thuận xu hướng)", 'status_str': "TĂNG 🟢",
    }


def analyze_single(symbol: str) -> Optional[Dict]:
    """Phân tích chi tiết 1 mã đơn (tra cứu Telegram)."""
    symbol = symbol.strip().upper()
    item   = get_live_stock_quote(symbol)
    exchange = item.get("exchange_name", "HOSE")
    price, vol, high, low, chg, _ = _parse_item(item)

    df = get_ticker_history(symbol, count=None, days=config.DTPRO_HISTORY_DAYS)
    if df is None or len(df) < 60:
        return None

    res = analyze_dtpro(
        df, symbol=symbol, exchange=exchange,
        live_price=price, live_high=high, live_low=low,
        live_vol=vol, change_pct=chg,
        st_len=config.DTPRO_ST_LEN, atr_len=config.DTPRO_ATR_LEN,
        st_mult=config.DTPRO_ST_MULT,
        ema_fast=config.DTPRO_EMA_FAST, ema_slow=config.DTPRO_EMA_SLOW,
        nw_h=config.DTPRO_NW_H, nw_mult=config.DTPRO_NW_MULT,
        nw_win=config.DTPRO_NW_WIN,
        cua_so_lookback=config.DTPRO_LOOKBACK,
        rr1=config.DTPRO_RR1, rr2=config.DTPRO_RR2,
    )
    if res:
        res['vni'] = get_vnindex_status()
    return res


def run_dtpro_screener(buy_only: bool = True, signal_only: bool = True) -> List[Dict]:
    """
    Quét toàn sàn HOSE + HNX theo bộ chỉ báo DÒNG TIỀN & XU HƯỚNG PRO:
    Tối ưu hóa: Lọc sơ bộ thanh khoản trước khi gọi API, phân tích song song 16 luồng siêu tốc.
    - buy_only=True: Chỉ lấy các mã có điểm MUA hoặc MUA MẠNH hôm nay
    - signal_only=True: Lấy các mã có tín hiệu (Mua hoặc Bán)
    """
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
            # Lọc sơ bộ thanh khoản ngay trên bảng giá snapshot trong 0.0001s
            price, vol, high, low, chg, raw_val = _parse_item(item)
            if price > 0 and vol > 0:
                est = raw_val if raw_val > 0 else price * 1000.0 * vol
                if est < min_val:
                    continue
            all_items.append((item, ex.upper()))

    print(f"[DTPro] Đã lọc {len(all_items)} mã đạt thanh khoản từ HOSE+HNX. Đang quét song song {config.MAX_WORKERS} luồng...")

    results = []
    workers = config.MAX_WORKERS
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(analyze_one, item, ex): (item, ex)
                   for item, ex in all_items}
        for future in concurrent.futures.as_completed(futures):
            try:
                res = future.result()
                if res is None:
                    continue
                if buy_only:
                    if not (res['buy_diamond'] or res['buy_standard']):
                        continue
                elif signal_only:
                    if not res['has_signal']:
                        continue
                results.append(res)
            except Exception:
                pass

    # Sắp xếp: Mua Mạnh (Diamond) lên đầu, tiếp đến Mua Chuẩn
    results.sort(key=lambda x: (
        -int(x.get('buy_diamond', False)),
        -int(x.get('buy_standard', False)),
        -int(x.get('has_signal', False)),
    ))
    tag = "ĐIỂM MUA (MUA & MUA MẠNH)" if buy_only else "tín hiệu"
    print(f"[DTPro] Hoàn tất — Tìm thấy {len(results)} mã có {tag}.")
    return results
