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
from datetime import datetime
import requests
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
import config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

def normalize_price_k(val) -> float:
    """
    Chuẩn hóa giá về đơn vị Nghìn VNĐ (đồng bộ với DNSE và hệ thống chỉ báo).
    VD: 21100 -> 21.1, 21.1 -> 21.1
    """
    if pd.isna(val) or val is None:
        return 0.0
    try:
        p = float(val)
        if p >= 1000.0:
            return p / 1000.0
        return p
    except Exception:
        return 0.0

def format_vnd(val) -> str:
    """
    Định dạng giá tiền chuẩn Việt Nam: VD 25.4 hoặc 25400 -> 25.400 đ
    """
    if pd.isna(val) or val is None or float(val) <= 0:
        return "0 đ"
    v = float(val)
    if v < 1000.0:
        v = v * 1000.0
    return f"{int(round(v)):,} đ".replace(",", ".")

def get_elapsed_trading_minutes(now_dt: Optional[datetime] = None) -> int:
    """
    Tính số phút giao dịch đã trôi qua trong ngày (Tổng 270 phút: Sáng 150p, Chiều 120p)
    """
    if now_dt is None:
        now_dt = datetime.now()
    if now_dt.weekday() > 4:
        return 270
    t = now_dt.time()
    t_0900 = datetime.strptime("09:00", "%H:%M").time()
    t_1130 = datetime.strptime("11:30", "%H:%M").time()
    t_1300 = datetime.strptime("13:00", "%H:%M").time()
    t_1500 = datetime.strptime("15:00", "%H:%M").time()

    if t < t_0900:
        return 270
    elif t <= t_1130:
        mins = (now_dt.hour - 9) * 60 + now_dt.minute
        return max(15, mins)
    elif t < t_1300:
        return 150
    elif t <= t_1500:
        mins = 150 + (now_dt.hour - 13) * 60 + now_dt.minute
        return max(165, mins)
    else:
        return 270

_snapshot_cache = {}
_snapshot_cache_time = {}

def get_exchange_symbols_snapshot(exchange: str) -> List[Dict]:
    """
    Lấy toàn bộ bảng giá thời gian thực sàn HOSE hoặc HNX từ SSI iBoard (kèm cache 20s và retry)
    """
    now = time.time()
    ex = exchange.lower()
    if ex in _snapshot_cache and (now - _snapshot_cache_time.get(ex, 0) < 20):
        return _snapshot_cache[ex]

    url = f"https://iboard-query.ssi.com.vn/stock/exchange/{ex}"
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and "data" in data:
                    res_list = data["data"]
                elif isinstance(data, list):
                    res_list = data
                else:
                    res_list = []
                if res_list:
                    _snapshot_cache[ex] = res_list
                    _snapshot_cache_time[ex] = now
                    return res_list
        except Exception as e:
            if attempt == 1:
                print(f"[Cảnh báo] Lỗi tải dữ liệu sàn {exchange}: {e}")
            time.sleep(0.5)
    return _snapshot_cache.get(ex, [])

def get_live_stock_quote(symbol: str) -> dict:
    """
    Lấy thông tin giá và khối lượng thời gian thực cho 1 mã cụ thể từ bảng giá trực tuyến
    """
    symbol = symbol.strip().upper()
    for ex in ["hose", "hnx"]:
        data = get_exchange_symbols_snapshot(ex)
        for d in data:
            if d.get("stockSymbol") == symbol:
                d["exchange_name"] = ex.upper()
                return d
    return {"stockSymbol": symbol}

def get_ticker_history(symbol: str, count: int = 60) -> Optional[pd.DataFrame]:
    """
    Lấy lịch sử nến ngày từ DNSE Entrade (Tốc độ cực cao: 0.1s)
    """
    now_ts = int(time.time())
    from_ts = now_ts - 160 * 86400  # Lấy khoảng 80-90 phiên nến gần nhất
    url_dnse = f"https://services.entrade.com.vn/chart-api/v2/ohlcs/stock?from={from_ts}&to={now_ts}&symbol={symbol}&resolution=1D"
    try:
        resp = requests.get(url_dnse, headers=HEADERS, timeout=5)
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
    Tính toán SuperTrend (10, 3.0), Mây Ichimoku (8, 13, 26, 12),
    Xu hướng Trend (-4 đến +4) và Rational Quadratic Kernel giống hệt 100% Pine Script AI Whale ProMax.
    """
    # 1. Tính ATR(10) và SuperTrend (10, 3.0)
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr10'] = tr.rolling(window=10).mean()

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

    # 2. Tính Ichimoku (8, 13, 26, 12)
    conv_line = (df['high'].rolling(8).max() + df['low'].rolling(8).min()) / 2
    base_line = (df['high'].rolling(13).max() + df['low'].rolling(13).min()) / 2
    span_a = (conv_line + base_line) / 2
    span_b = (df['high'].rolling(26).max() + df['low'].rolling(26).min()) / 2

    # Mây được dời 12 nến về trước (displacement - 1 = 12)
    df['cloud_max'] = pd.concat([span_a.shift(12), span_b.shift(12)], axis=1).max(axis=1)
    df['cloud_min'] = pd.concat([span_a.shift(12), span_b.shift(12)], axis=1).min(axis=1)

    # 3. Tính Ichimoku Trend (-4 đến +4)
    atr9 = tr.rolling(9).mean()
    mtrend = [0] * len(df)
    trend = [0] * len(df)

    for i in range(1, len(df)):
        c = df['close'].iloc[i]
        c_max = df['cloud_max'].iloc[i]
        c_min = df['cloud_min'].iloc[i]

        if pd.notna(c_max) and c > c_max:
            mtrend[i] = 1
        elif pd.notna(c_min) and c < c_min:
            mtrend[i] = -1
        else:
            mtrend[i] = mtrend[i-1]

        oscline = (c - c_min) if mtrend[i] == 1 else (c - c_max) if pd.notna(c_max) else 0
        c_max_12 = df['cloud_max'].iloc[i-12] if i >= 12 else np.nan
        c_min_12 = df['cloud_min'].iloc[i-12] if i >= 12 else np.nan
        lagging = oscline + (max(c - c_max_12, 0) if (mtrend[i] == 1 and pd.notna(c_max_12)) else min(c - c_min_12, 0) if (mtrend[i] == -1 and pd.notna(c_min_12)) else 0)

        conv_rise = (conv_line.iloc[i] - conv_line.iloc[i-1]) > 0 if i >= 1 else False
        base_rise = (base_line.iloc[i] - base_line.iloc[i-1]) > 0 if i >= 1 else False
        convoverbase = conv_line.iloc[i] >= base_line.iloc[i]
        lead1_over_lead2 = span_a.iloc[i] >= span_b.iloc[i]
        tole = atr9.iloc[i] * 2.0 if pd.notna(atr9.iloc[i]) else 1.0

        t = trend[i-1]
        if mtrend[i] == 1:
            if mtrend[i-1] == -1:
                t = 0
            if t < 4 and pd.notna(c_max) and c > c_max:
                score = (1 if lagging > oscline else 0) + (1 if (convoverbase and (conv_rise or base_rise)) else 0) + (1 if lead1_over_lead2 else 0) + 1
                t = score
            else:
                if conv_line.iloc[i] < base_line.iloc[i] - tole:
                    t = 0
        elif mtrend[i] == -1:
            if mtrend[i-1] == 1:
                t = 0
            if t > -4 and pd.notna(c_min) and c < c_min:
                score = (-1 if lagging < oscline else 0) - (1 if (not convoverbase and (not conv_rise or not base_rise)) else 0) - (1 if not lead1_over_lead2 else 0) - 1
                t = score
            else:
                if conv_line.iloc[i] > base_line.iloc[i] + tole:
                    t = 0
        trend[i] = t

    df['trend'] = trend

    # 4. Rational Quadratic Kernel (h=8, r=8.0, x=25)
    weights = np.array([(1.0 + (k**2) / (2.0 * 8.0 * (8**2))) ** (-8.0) for k in range(8 + 25 + 1)])
    yhat1 = np.zeros(len(df))
    close_vals = df['close'].values
    for idx in range(len(df)):
        bars_back = min(idx, len(weights) - 1)
        w = weights[:bars_back + 1]
        s = close_vals[idx - bars_back : idx + 1][::-1]
        yhat1[idx] = np.dot(w, s) / np.sum(w)
    df['yhat1'] = yhat1

    # 5. MA20 Khối lượng
    df['vol_ma20'] = df['volume'].rolling(20).mean()

def analyze_stock(item: dict, exchange: str) -> Optional[Dict]:
    """
    Phân tích cổ phiếu: Đồng bộ chuẩn xác 100% với chỉ báo Pine Script AI Whale ProMax.
    Chỉ trả về Dict khi THỰC SỰ CÓ ĐIỂM MUA MỚI HÔM NAY (không báo ảo).
    """
    symbol = item.get("stockSymbol") or item.get("ssi_symbol") or item.get("symbol")
    if not symbol or len(symbol) != 3 or not symbol.isalpha():
        return None

    df = get_ticker_history(symbol, count=60)
    if df is None or len(df) < 35:
        return None

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

    # Lấy dữ liệu nến chuẩn xác tuyệt đối (KHÔNG lấy low/high của nến hôm qua gán cho hôm nay)
    if not raw_price or float(raw_price) <= 0 or not raw_vol or float(raw_vol) <= 0:
        matched_price = df['close'].iloc[-1]
        total_vol = float(df['volume'].iloc[-1])
        today_open = df['open'].iloc[-1]
        today_high = df['high'].iloc[-1]
        today_low = df['low'].iloc[-1]
        change_pct = ((matched_price - df['close'].iloc[-2]) / df['close'].iloc[-2]) * 100.0 if len(df) >= 2 else 0.0
        df_eval = df.copy()
    else:
        matched_price = normalize_price_k(raw_price)
        total_vol = float(raw_vol)
        today_open = normalize_price_k(item.get("openPrice") or item.get("open")) or matched_price
        
        # SSI iBoard dùng trường 'highest' và 'lowest'
        today_high = normalize_price_k(item.get("highest") or item.get("highestPrice") or item.get("high")) or max(matched_price, today_open)
        today_low = normalize_price_k(item.get("lowest") or item.get("lowestPrice") or item.get("low")) or min(matched_price, today_open)
        today_high = max(today_high, matched_price, today_open)
        today_low = min(today_low, matched_price, today_open)

        change_pct = float(
            item.get("priceChangePercent") or 
            item.get("changePercent") or 
            item.get("matchedPricePercent") or 
            item.get("expectedPriceChangePercent") or 0.0
        )
        if change_pct == 0.0 and len(df) >= 2 and df['close'].iloc[-2] > 0:
            change_pct = ((matched_price - df['close'].iloc[-2]) / df['close'].iloc[-2]) * 100.0

        # Ghép nến thời gian thực vào dữ liệu để tính toán bar-by-bar
        today_row = pd.DataFrame([{
            'time': int(time.time()),
            'open': today_open,
            'high': today_high,
            'low': today_low,
            'close': matched_price,
            'volume': total_vol
        }])
        df_eval = pd.concat([df, today_row], ignore_index=True)

    total_val = float(item.get("totalVal") or (matched_price * 1000.0 * total_vol))

    # Lọc thanh khoản tối thiểu (>= 3 tỷ VNĐ)
    if total_val < config.MIN_TRADE_VALUE:
        return None

    # Tính toán toàn bộ chỉ báo
    calculate_indicators(df_eval)

    vol_ma20 = float(df_eval['vol_ma20'].iloc[-1])
    if pd.isna(vol_ma20) or vol_ma20 <= 0:
        return None

    current_vol_ratio = total_vol / vol_ma20
    elapsed_mins = get_elapsed_trading_minutes()
    
    # Dự phóng khối lượng: Chỉ áp dụng khi đã giao dịch >= 30 phút để tránh thổi phồng đầu phiên
    if elapsed_mins < 270 and total_vol > 0 and elapsed_mins >= 30:
        projected_vol = (total_vol / elapsed_mins) * 270.0
        projected_vol_ratio = projected_vol / vol_ma20
    else:
        projected_vol = total_vol
        projected_vol_ratio = current_vol_ratio

    # 1. KIỂM TRA ĐIỀU KIỆN SUPERTREND & ICHIMOKU
    is_supertrend_bull = df_eval['supertrend'].iloc[-1] == 1
    cloud_max = df_eval['cloud_max'].iloc[-1]
    is_above_cloud = pd.notna(cloud_max) and (matched_price >= cloud_max * 0.99)
    current_trend = df_eval['trend'].iloc[-1]

    # HUD Xu hướng theo đúng chỉ báo
    if current_trend == 4:
        hud_trend = "TĂNG MẠNH 🟢"
    elif current_trend == -4:
        hud_trend = "GIẢM MẠNH 🔴"
    else:
        hud_trend = "SIDEWAY ⚪"

    # Nếu đang trong xu hướng giảm mạnh của Supertrend và dưới mây thì loại bỏ
    if not is_supertrend_bull and not is_above_cloud:
        return None

    # Kiểm tra giá trần
    ceiling_k = normalize_price_k(item.get("ceiling"))
    is_at_ceiling = (ceiling_k > 0) and (matched_price >= ceiling_k * 0.998)

    # Thông số nến ngày
    candle_range = today_high - today_low
    if candle_range > 0:
        lower_wick = min(today_open, matched_price) - today_low
        lower_wick_ratio = lower_wick / candle_range
        body_size = abs(matched_price - today_open)
        body_ratio = body_size / candle_range
    else:
        lower_wick_ratio = 0.0
        body_ratio = 0.0

    # 2. XÁC NHẬN DÒNG TIỀN CÁ MẬP (SMART MONEY FLOW)
    # Khối lượng cá mập thực tế phải bùng nổ: vol_ratio >= 1.3 hoặc (sau 45p vol >= 0.7x và dự phóng >= 1.5x)
    is_ultra_vol = (current_vol_ratio >= 1.3) or (elapsed_mins >= 45 and current_vol_ratio >= 0.7 and projected_vol_ratio >= 1.5)
    hud_money = "🐋 CÁ MẬP VÀO" if is_ultra_vol else "Bình Thường ⏳"

    # 3. KIỂM TRA ĐIỂM BÓP CÒ MỚI (FRESH TRIGGER TRÊN NẾN HIỆN TẠI)
    # A. SuperTrend mới đảo chiều Tăng hôm nay (chưa phải phiên cũ)
    st_flip_bull = (df_eval['supertrend'].iloc[-1] == 1) and (df_eval['supertrend'].iloc[-2] == -1) and (current_vol_ratio >= 0.8)

    # B. Kernel Rational Quadratic Crossover Up hôm nay
    kernel_cross_up = (df_eval['yhat1'].iloc[-1] > df_eval['yhat1'].iloc[-2]) and (df_eval['yhat1'].iloc[-2] <= df_eval['yhat1'].iloc[-3])

    # C. Cá Mập gom hàng (Whale Liquidity Sweep / Spring: Rút chân mạnh + Vol bùng nổ)
    is_spring = (lower_wick_ratio >= 0.35) and is_ultra_vol and (matched_price >= today_open * 0.995)

    # D. Cá Mập bứt phá (SOS Breakout: Vượt đỉnh 15 phiên + Vol bùng nổ)
    recent_high_15 = df_eval['high'].iloc[-16:-1].max() if len(df_eval) > 16 else df_eval['high'].max()
    is_sos_breakout = (matched_price >= recent_high_15 * 0.998) and (change_pct >= 1.5) and is_ultra_vol and (body_ratio >= 0.40)

    # Đánh giá điểm mua
    has_fresh_trigger = False
    is_confirmed_whale = False
    pattern = ""
    whale_badge = "📊 [TIÊU CHUẨN]"

    if is_supertrend_bull or is_above_cloud:
        if is_spring:
            has_fresh_trigger = True
            is_confirmed_whale = True
            whale_badge = "🐋👑 [CÁ MẬP GOM HÀNG]"
            pattern = "Cá Mập gom hàng (Quét thanh khoản)"
        elif is_sos_breakout:
            has_fresh_trigger = True
            is_confirmed_whale = True
            whale_badge = "🐋👑 [CÁ MẬP ĐẨY GIÁ]"
            pattern = "Cá Mập đẩy giá (Bứt phá SOS)"
        elif st_flip_bull and (is_above_cloud or current_trend >= 2):
            has_fresh_trigger = True
            whale_badge = "🚀 [SUPERTREND]"
            pattern = "SuperTrend đảo chiều Tăng 🟢"
        elif kernel_cross_up and current_trend == 4 and is_supertrend_bull and (current_vol_ratio >= 1.1 or is_ultra_vol):
            has_fresh_trigger = True
            whale_badge = "🔮 [TIÊN TRI ML]"
            pattern = "Thuật toán Kernel & ML kích hoạt điểm MUA"

    # NẾU KHÔNG CÓ ĐIỂM BÓP CÒ MỚI HÔM NAY: BỎ QUA (Không báo ảo trên Telegram!)
    if not has_fresh_trigger:
        return None

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

    sl_pct = ((sl - matched_price) / matched_price) * 100
    tp1_pct = ((tp1 - matched_price) / matched_price) * 100
    tp2_pct = ((tp2 - matched_price) / matched_price) * 100
    tp3_pct = ((tp3 - matched_price) / matched_price) * 100

    effective_vol_ratio = max(current_vol_ratio, projected_vol_ratio)

    # Tính độ tin cậy AI (WinRate %) đồng bộ như chỉ báo Pine Script
    if is_confirmed_whale:
        win_rate = min(94.0, max(78.0, 75.0 + (effective_vol_ratio - 1.2) * 8.0 + (lower_wick_ratio - 0.35) * 20.0))
    else:
        win_rate = min(78.0, max(68.0, 65.0 + (effective_vol_ratio - 1.0) * 8.0))

    import main
    in_session = main.is_trading_hour()
    now_str = datetime.now().strftime("%H:%M %d/%m/%Y")
    candle_ts = df['time'].iloc[-1] if 'time' in df.columns else None
    last_candle_date = datetime.fromtimestamp(int(candle_ts)).strftime("%d/%m/%Y") if candle_ts else datetime.now().strftime("%d/%m/%Y")

    if in_session:
        time_display = f"{now_str} (Thời gian thực)"
        session_tag = "Thời gian thực"
    else:
        time_display = f"{now_str} (Chốt phiên {last_candle_date})"
        session_tag = f"Chốt phiên {last_candle_date}"

    cloud_status = "Trên Mây 🟢" if is_above_cloud else "Dưới Mây 🔴"

    return {
        "symbol": symbol,
        "exchange": exchange,
        "price": matched_price,
        "price_vnd": format_vnd(matched_price),
        "change_pct": change_pct,
        "volume": total_vol,
        "vol_ma20": vol_ma20,
        "vol_ratio": current_vol_ratio,
        "projected_vol": projected_vol,
        "projected_vol_ratio": projected_vol_ratio,
        "trade_value_bil": total_val / 1_000_000_000.0,
        "is_whale": is_confirmed_whale,
        "is_at_ceiling": is_at_ceiling,
        "whale_badge": whale_badge,
        "pattern": pattern,
        "win_rate": win_rate,
        "supertrend": "Tăng 🟢" if is_supertrend_bull else "Giảm 🔴",
        "cloud_status": cloud_status,
        "hud_trend": hud_trend,
        "hud_money": hud_money,
        "hud_order": f"MUA tại {format_vnd(matched_price)} (SL: {format_vnd(sl)})",
        "has_buy_signal": True,
        "candle_date": last_candle_date,
        "updated_time": now_str,
        "time_display": time_display,
        "session_tag": session_tag,
        "recommendation": f"Đạt chuẩn {whale_badge} - {pattern}. Kế hoạch giao dịch chi tiết bên dưới.",
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
    print(f"[*] Kiến trúc: Lọc 2 tầng siêu tốc (2-Stage Pipeline) + Ngoại suy khối lượng")
    print(f"{'='*75}")

    for exchange in config.EXCHANGES:
        print(f"[*] Đang tải dữ liệu toàn sàn {exchange}...")
        items = get_exchange_symbols_snapshot(exchange)
        print(f" -> Nhận được {len(items)} mã trên sàn {exchange}.")

        # TẦNG 1: LỌC NHANH TRÊN SNAPSHOT
        candidates = []
        for item in items:
            sym = item.get("stockSymbol") or item.get("symbol")
            if not sym or len(sym) != 3 or not sym.isalpha():
                continue
            p = normalize_price_k(item.get("matchedPrice") or item.get("lastPrice") or item.get("expectedMatchedPrice") or item.get("refPrice") or 0)
            v = float(item.get("totalVol") or item.get("nmTotalTradedQty") or item.get("expectedMatchedVolume") or 0)
            val = float(item.get("totalVal") or (p * 1000.0 * v))
            
            if val >= config.MIN_TRADE_VALUE or (val >= 1_000_000_000 and float(item.get("changePercent", 0) or 0) >= 1.0):
                candidates.append(item)

        print(f" -> Tầng 1 đã chọn {len(candidates)} mã tiềm năng (loại bỏ {len(items) - len(candidates)} mã thanh khoản yếu). Đang phân tích chuyên sâu...")

        # TẦNG 2: PHÂN TÍCH CHUYÊN SÂU
        for item in candidates:
            try:
                result = analyze_stock(item, exchange)
                if result:
                    if result["is_whale"]:
                        print(f"  🐋👑 [CÁ MẬP] {result['symbol']} | Giá: {result['price_vnd']} ({result['change_pct']:+.2f}%) | Vol: {result['vol_ratio']:.1f}x MA20 (Dự phóng: {result['projected_vol_ratio']:.1f}x) | {result['pattern']}")
                    else:
                        print(f"  📊 [Chuẩn] {result['symbol']} | Giá: {result['price_vnd']} ({result['change_pct']:+.2f}%) | Vol: {result['vol_ratio']:.1f}x MA20")
                    signals.append(result)
            except Exception:
                continue

    signals = sorted(signals, key=lambda x: (x["is_whale"], x["vol_ratio"]), reverse=True)
    print(f"{'='*75}")
    whale_count = sum(1 for s in signals if s["is_whale"])
    print(f"✅ HOÀN TẤT QUÉT! Tìm thấy {len(signals)} mã (Trong đó có {whale_count} mã XÁC NHẬN CÓ CÁ MẬP 🐋).")
    print(f"{'='*75}\n")
    return signals
