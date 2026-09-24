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
        vni_trend_map=get_vnindex_trend_map(config.DTPRO_HISTORY_DAYS),
    )
    if res:
        res['vni'] = get_vnindex_status()
    return res


_vni_cache = None
_vni_cache_time = 0

_vni_hist_map = {}
_vni_hist_time = 0

def get_vnindex_trend_map(days: int = 1000) -> dict:
    """Lấy lịch sử xu hướng VNINDEX map theo timestamp."""
    global _vni_hist_map, _vni_hist_time
    now = time.time()
    if _vni_hist_map and (now - _vni_hist_time < 300):
        return _vni_hist_map

    try:
        from screener import get_session
        s = get_session()
        now_ts = int(now)
        from_ts = now_ts - days * 86400
        u = f"https://services.entrade.com.vn/chart-api/v2/ohlcs/index?from={from_ts}&to={now_ts}&symbol=VNINDEX&resolution=1D"
        r = s.get(u, timeout=(2.0, 4.0))
        if r.status_code == 200:
            d = r.json()
            if 'c' in d and len(d['c']) > 20:
                df_vni = pd.DataFrame({
                    'time': d['t'],
                    'open': d['o'],
                    'high': d['h'],
                    'low': d['l'],
                    'close': d['c'],
                    'volume': d['v']
                })
                from dtpro_indicators import calc_supertrend
                st_dir, _ = calc_supertrend(df_vni, st_len=config.DTPRO_ST_LEN, atr_mult=config.DTPRO_ST_MULT, atr_len=config.DTPRO_ATR_LEN)
                is_up = st_dir == 1
                _vni_hist_map = {d['t'][i]: bool(is_up.iloc[i]) for i in range(len(d['t']))}
                _vni_hist_time = now
    except Exception:
        pass
    return _vni_hist_map

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
        from_ts = now_ts - 400 * 86400
        u = f"https://services.entrade.com.vn/chart-api/v2/ohlcs/index?from={from_ts}&to={now_ts}&symbol=VNINDEX&resolution=1D"
        r = s.get(u, timeout=(2.0, 4.0))
        if r.status_code == 200:
            d = r.json()
            if 'c' in d and len(d['c']) > 60:
                df_vni = pd.DataFrame({
                    'time': d['t'],
                    'open': d['o'],
                    'high': d['h'],
                    'low': d['l'],
                    'close': d['c'],
                    'volume': d['v']
                })
                from dtpro_indicators import calc_supertrend, calc_ema
                st_dir, _ = calc_supertrend(df_vni, st_len=config.DTPRO_ST_LEN, atr_mult=config.DTPRO_ST_MULT, atr_len=config.DTPRO_ATR_LEN)
                dir_val = int(st_dir.iloc[-1])
                c_series = df_vni['close']
                cur_p = float(c_series.iloc[-1])
                prev_p = float(c_series.iloc[-2]) if len(c_series) > 1 else cur_p
                chg = (cur_p - prev_p) / prev_p * 100

                # Dùng EMA20/EMA50 nhất quán với Pine Script f_trend()
                # KHÔNG dùng SMA + threshold — đó là logic sai
                ema20 = float(calc_ema(c_series, config.DTPRO_EMA_FAST).iloc[-1])
                ema50 = float(calc_ema(c_series, config.DTPRO_EMA_SLOW).iloc[-1])
                if cur_p > ema20 and ema20 > ema50:
                    state = "TĂNG"
                    state_str = "🟢 TĂNG"
                elif cur_p < ema20 and ema20 < ema50:
                    state = "GIẢM"
                    state_str = "🔴 GIẢM"
                else:
                    state = "NGANG"
                    state_str = "⚪ NGANG"
                ma20 = ema20  # backward compat

                _vni_cache = {
                    'price': cur_p,
                    'chg_pct': chg,
                    'ma20': ma20,
                    'ema20': ema20,
                    'ema50': ema50,
                    'st_dir': dir_val,
                    'state': state,
                    'state_str': state_str,
                    'is_uptrend': (state == "TĂNG"),
                    'label': state_str,
                    'status_str': state_str,
                }
                _vni_cache_time = now
                return _vni_cache
    except Exception:
        pass

    if _vni_cache is not None:
        return _vni_cache

    return {
        'price': 0.0, 'chg_pct': 0.0, 'ma20': 0.0, 'st_dir': 1,
        'state': "TĂNG", 'state_str': "🟢 TĂNG", 'is_uptrend': True,
        'label': "🟢 TĂNG", 'status_str': "🟢 TĂNG",
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
        vni_trend_map=get_vnindex_trend_map(config.DTPRO_HISTORY_DAYS),
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
