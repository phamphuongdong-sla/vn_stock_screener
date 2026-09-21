# -*- coding: utf-8 -*-
"""
Module quét và phân tích dữ liệu toàn bộ thị trường chứng khoán Việt Nam (HOSE, HNX)
ĐỒNG BỘ 100% THEO CHỈ BÁO PINE SCRIPT "AI CÁ MẬP PROMAX":
1. Xu hướng SuperTrend (10, 3.0)
2. Mây Ichimoku (8, 13, 26, 12) - Giá nằm trên mây
3. Tiêu chuẩn Cá Mập khắt khe: Volume bùng nổ >= 1.5x MA20 + Nến rút chân quét thanh khoản (Spring) / Vượt đỉnh (SOS)
4. Định dạng tiền tệ chuẩn VNĐ (VD: 25.400 đ)
"""

import time
import requests
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
import config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

def format_vnd(val: float) -> str:
    """
    Định dạng giá tiền chuẩn Việt Nam: VD 25.4 -> 25.400 đ
    """
    if pd.isna(val) or val <= 0:
        return "0 đ"
    v = val * 1000 if val < 1000 else val
    return f"{int(round(v)):,} đ".replace(",", ".")

def get_exchange_symbols_snapshot(exchange: str) -> List[Dict]:
    """
    Lấy toàn bộ bảng giá thời gian thực sàn HOSE hoặc HNX từ SSI iBoard
    """
    exchange_lower = exchange.lower()
    url = f"https://iboard-query.ssi.com.vn/stock/exchange/{exchange_lower}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and "data" in data:
                return data["data"]
            elif isinstance(data, list):
                return data
    except Exception as e:
        print(f"[Cảnh báo] Lỗi tải dữ liệu sàn {exchange}: {e}")
    return []

def get_ticker_history(symbol: str, count: int = 60) -> Optional[pd.DataFrame]:
    """
    Lấy lịch sử nến ngày từ DNSE Entrade (Tốc độ cao & cực kỳ ổn định)
    """
    url_dnse = f"https://services.entrade.com.vn/chart-api/v2/ohlcs/stock?from=1650000000&to=2100000000&symbol={symbol}&resolution=1D"
    try:
        resp = requests.get(url_dnse, headers=HEADERS, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            if data and "t" in data and len(data["t"]) >= 30:
                df = pd.DataFrame({
                    "time": data["t"],
                    "open": data["o"],
                    "high": data["h"],
                    "low": data["l"],
                    "close": data["c"],
                    "volume": data["v"]
                })
                return df.tail(count).reset_index(drop=True)
    except Exception:
        pass

    return None

def calculate_indicators(df: pd.DataFrame):
    """
    Tính toán SuperTrend (10, 3.0) và Mây Ichimoku (8, 13, 26, 12) giống hệt Pine Script
    """
    # 1. Tính ATR(10)
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr10'] = tr.rolling(window=10).mean()

    # 2. Tính SuperTrend (10, 3.0)
    hl2 = (df['high'] + df['low']) / 2
    upper_band = hl2 + (df['atr10'] * 3.0)
    lower_band = hl2 - (df['atr10'] * 3.0)

    trend_st = [1] * len(df)
    bien_tren = list(upper_band)
    bien_duoi = list(lower_band)

    for i in range(1, len(df)):
        if df['close'].iloc[i-1] < bien_tren[i-1]:
            bien_tren[i] = min(upper_band.iloc[i], bien_tren[i-1])
        else:
            bien_tren[i] = upper_band.iloc[i]

        if df['close'].iloc[i-1] > bien_duoi[i-1]:
            bien_duoi[i] = max(lower_band.iloc[i], bien_duoi[i-1])
        else:
            bien_duoi[i] = lower_band.iloc[i]

        if df['close'].iloc[i] > bien_tren[i]:
            trend_st[i] = 1
        elif df['close'].iloc[i] < bien_duoi[i]:
            trend_st[i] = -1
        else:
            trend_st[i] = trend_st[i-1]

    df['supertrend'] = trend_st

    # 3. Tính Ichimoku (8, 13, 26, 12)
    conv_line = (df['high'].rolling(8).max() + df['low'].rolling(8).min()) / 2
    base_line = (df['high'].rolling(13).max() + df['low'].rolling(13).min()) / 2
    span_a = (conv_line + base_line) / 2
    span_b = (df['high'].rolling(26).max() + df['low'].rolling(26).min()) / 2

    # Mây được dời 12 nến về trước (displacement - 1)
    df['cloud_max'] = pd.concat([span_a.shift(12), span_b.shift(12)], axis=1).max(axis=1)
    df['cloud_min'] = pd.concat([span_a.shift(12), span_b.shift(12)], axis=1).min(axis=1)

    # MA20 Khối lượng
    df['vol_ma20'] = df['volume'].rolling(20).mean()

def analyze_stock(item: dict, exchange: str) -> Optional[Dict]:
    """
    Phân tích cổ phiếu: Kết hợp cả SuperTrend + Ichimoku + Bộ lọc Cá mập
    """
    symbol = item.get("stockSymbol") or item.get("ssi_symbol") or item.get("symbol")
    if not symbol or len(symbol) != 3 or not symbol.isalpha():
        return None

    df = get_ticker_history(symbol, count=60)
    if df is None or len(df) < 35:
        return None

    matched_price = item.get("matchedPrice", 0) or item.get("lastPrice", 0) or item.get("close", 0)
    total_vol = item.get("totalVol", 0) or item.get("nmTotalTradedQty", 0)

    # Nếu ngoài giờ giao dịch hoặc phiên chưa bắt đầu, tự động lấy nến phiên gần nhất
    if matched_price <= 0 or total_vol <= 0:
        matched_price = df['close'].iloc[-1]
        total_vol = df['volume'].iloc[-1]
        today_open = df['open'].iloc[-1]
        today_high = df['high'].iloc[-1]
        today_low = df['low'].iloc[-1]
        change_pct = ((matched_price - df['close'].iloc[-2]) / df['close'].iloc[-2]) * 100 if len(df) >= 2 else 0
    else:
        today_open = item.get("open", 0) or df['open'].iloc[-1]
        today_high = item.get("high", 0) or df['high'].iloc[-1]
        today_low = item.get("low", 0) or df['low'].iloc[-1]
        change_pct = item.get("changePercent", 0) or item.get("matchedPricePercent", 0) or 0

    total_val = item.get("totalVal", 0) or (matched_price * 1000 * total_vol if matched_price < 1000 else matched_price * total_vol)

    # Lọc thanh khoản tối thiểu (>= 3 tỷ VNĐ)
    if total_val < config.MIN_TRADE_VALUE:
        return None

    # Tính toán toàn bộ chỉ báo
    calculate_indicators(df)

    vol_ma20 = df['vol_ma20'].iloc[-1]
    if pd.isna(vol_ma20) or vol_ma20 <= 0:
        return None

    vol_ratio = total_vol / vol_ma20

    # 1. KIỂM TRA ĐIỀU KIỆN SUPERTREND & ICHIMOKU
    is_supertrend_bull = df['supertrend'].iloc[-1] == 1
    cloud_max = df['cloud_max'].iloc[-1]
    is_above_cloud = pd.notna(cloud_max) and (matched_price >= cloud_max * 0.99)

    # Nếu đang trong xu hướng giảm mạnh của Supertrend và dưới mây thì loại bỏ
    if not is_supertrend_bull and not is_above_cloud:
        return None

    # Thông số nến ngày
    today_open = item.get("open", 0) or df['open'].iloc[-1]
    today_high = item.get("high", 0) or df['high'].iloc[-1]
    today_low = item.get("low", 0) or df['low'].iloc[-1]
    change_pct = item.get("changePercent", 0) or item.get("matchedPricePercent", 0) or 0

    candle_range = today_high - today_low
    if candle_range <= 0:
        return None

    lower_wick = min(today_open, matched_price) - today_low
    lower_wick_ratio = lower_wick / candle_range
    body_size = abs(matched_price - today_open)
    body_ratio = body_size / candle_range

    # 2. XÁC NHẬN DẤU CHÂN CÁ MẬP (SMART MONEY)
    is_spring = lower_wick_ratio >= config.WHALE_LOWER_WICK_RATIO
    recent_high_15 = df['high'].tail(15).max()
    is_sos_breakout = (matched_price >= recent_high_15 * 0.98) and (change_pct >= 2.0) and (body_ratio >= 0.60)
    
    # Volume siêu khủng (>= 1.5x MA20 hoặc cao nhất 15 phiên)
    is_ultra_vol = (vol_ratio >= config.WHALE_VOLUME_RATIO) or (total_vol >= df['volume'].tail(15).max())
    is_confirmed_whale = is_ultra_vol and (is_spring or is_sos_breakout)

    if config.STRICT_WHALE_ONLY and not is_confirmed_whale:
        return None

    # Nếu không phải cá mập và cũng không có tín hiệu kỹ thuật thì bỏ qua
    if not is_confirmed_whale and (vol_ratio < 1.1 or (lower_wick_ratio < 0.25 and not is_sos_breakout)):
        return None

    # Tên & Logo hiển thị
    if is_confirmed_whale:
        whale_badge = "🐋👑 [CÁ MẬP]"
        pattern = "🐋 CÁ MẬP GOM HÀNG (Quét SL)" if is_spring else "🐋 CÁ MẬP ĐẨY GIÁ (SOS Breakout)"
    else:
        whale_badge = "📊 [TIÊU CHUẨN]"
        pattern = "Tín hiệu hồi phục / Bứt phá"

    # 3. TÍNH TOÁN TP1, TP2, TP3 VÀ STOP LOSS (THEO ĐÚNG PINE SCRIPT)
    recent_swing_low = df['low'].tail(10).min()
    sl = min(today_low * 0.99, recent_swing_low)
    risk = matched_price - sl
    if risk <= 0:
        risk = matched_price * 0.03
        sl = matched_price - risk

    tp1 = matched_price + (risk * config.RR_TP1)
    tp2 = matched_price + (risk * config.RR_TP2)
    tp3 = matched_price + (risk * config.RR_TP3)

    # Tính tỷ lệ % lợi nhuận và cắt lỗ
    sl_pct = ((sl - matched_price) / matched_price) * 100
    tp1_pct = ((tp1 - matched_price) / matched_price) * 100
    tp2_pct = ((tp2 - matched_price) / matched_price) * 100
    tp3_pct = ((tp3 - matched_price) / matched_price) * 100

    # Tính độ tin cậy AI (WinRate %) đồng bộ như chỉ báo Pine Script
    if is_confirmed_whale:
        win_rate = min(94.0, max(78.0, 75.0 + (vol_ratio - 1.5) * 8.0 + (lower_wick_ratio - 0.40) * 25.0))
    else:
        win_rate = min(77.0, max(65.0, 62.0 + (vol_ratio - 1.0) * 8.0))

    return {
        "symbol": symbol,
        "exchange": exchange,
        "price": matched_price,
        "price_vnd": format_vnd(matched_price),
        "change_pct": change_pct,
        "volume": total_vol,
        "vol_ma20": vol_ma20,
        "vol_ratio": vol_ratio,
        "trade_value_bil": total_val / 1_000_000_000,
        "is_whale": is_confirmed_whale,
        "whale_badge": whale_badge,
        "pattern": pattern,
        "win_rate": win_rate,
        "supertrend": "Tăng 🟢" if is_supertrend_bull else "Giảm 🔴",
        "sl": sl,
        "sl_vnd": format_vnd(sl),
        "sl_pct": sl_pct,
        "tp1": tp1,
        "tp1_vnd": format_vnd(tp1),
        "tp1_pct": tp1_pct,
        "tp2": tp2,
        "tp2_vnd": format_vnd(tp2),
        "tp2_pct": tp2_pct,
        "tp3": tp3,
        "tp3_vnd": format_vnd(tp3),
        "tp3_pct": tp3_pct
    }

def run_screener() -> List[Dict]:
    signals = []
    print(f"\n{'='*75}")
    print(f"🚀 BẮT ĐẦU QUÉT THỊ TRƯỜNG CHỨNG KHOÁN VIỆT NAM ({', '.join(config.EXCHANGES)})")
    print(f"[*] Hợp lưu: SuperTrend + Mây Ichimoku + Bộ Lọc Cá Mập Siêu Bùng Nổ")
    print(f"{'='*75}")

    for exchange in config.EXCHANGES:
        print(f"[*] Đang tải dữ liệu toàn sàn {exchange}...")
        items = get_exchange_symbols_snapshot(exchange)
        print(f" -> Nhận được {len(items)} mã trên sàn {exchange}. Đang phân tích kỹ thuật...")

        for idx, item in enumerate(items):
            try:
                result = analyze_stock(item, exchange)
                if result:
                    if result["is_whale"]:
                        print(f"  🐋👑 [CÁ MẬP] {result['symbol']} | Giá: {result['price_vnd']} ({result['change_pct']:+.2f}%) | Vol: {result['vol_ratio']:.1f}x MA20 | {result['pattern']}")
                    else:
                        print(f"  📊 [Chuẩn] {result['symbol']} | Giá: {result['price_vnd']} ({result['change_pct']:+.2f}%) | Vol: {result['vol_ratio']:.1f}x MA20")
                    signals.append(result)
            except Exception:
                continue
                
    # Ưu tiên xếp các mã CÁ MẬP lên đầu
    signals = sorted(signals, key=lambda x: (x["is_whale"], x["vol_ratio"]), reverse=True)

    print(f"{'='*75}")
    whale_count = sum(1 for s in signals if s["is_whale"])
    print(f"✅ HOÀN TẤT QUÉT! Tìm thấy {len(signals)} mã (Trong đó có {whale_count} mã XÁC NHẬN CÓ CÁ MẬP 🐋).")
    print(f"{'='*75}\n")
    return signals
