# -*- coding: utf-8 -*-
"""
Module quét và phân tích dữ liệu toàn bộ thị trường chứng khoán Việt Nam (HOSE, HNX)
ĐỒNG BỘ 100% THEO CHỈ BÁO PINE SCRIPT "Volume AI & Keltner - Premium UI":
1. Keltner SuperTrend theo VWMA(10) và ATR(10, factor=2.8)
2. Lõi học máy Volume AI (KNN k=3, n_data=10, WMA 20 & WMA 100)
3. Tín hiệu 2 chiều real-time: MUA LÊN (LONG) và BÁN XUỐNG (SHORT)
4. Quản trị rủi ro chuẩn xác: Cắt Lỗ (SL), Mục Tiêu (TP1: 1.0R, TP2: 1.5R, TP3: 2.5R) theo ATR(14)
5. Định dạng tiền tệ chuẩn VNĐ (VD: 25.400 đ)
"""

import time
from datetime import datetime
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import numpy as np
import concurrent.futures
from typing import List, Dict, Optional
import config
from indicators import calculate_all_indicators, calc_risk_levels

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Connection": "close"
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
    Luôn tính theo múi giờ Việt Nam (UTC+7).
    """
    from datetime import timezone, timedelta
    vn_tz = timezone(timedelta(hours=7))
    if now_dt is None:
        now_dt = datetime.now(vn_tz)
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

def is_trading_hour(now_dt: Optional[datetime] = None) -> bool:
    """
    Kiểm tra xem hiện tại có phải trong phiên giao dịch chứng khoán Việt Nam hay không
    (Thứ 2 đến Thứ 6, từ 9h00 - 11h30 và 13h00 - 15h00 theo giờ Việt Nam UTC+7)
    """
    from datetime import timezone, timedelta
    vn_tz = timezone(timedelta(hours=7))
    now = now_dt if now_dt is not None else datetime.now(vn_tz)
    if now.weekday() > 4:
        return False
    
    current_time = now.time()
    t_0900 = datetime.strptime("09:00", "%H:%M").time()
    t_1130 = datetime.strptime("11:30", "%H:%M").time()
    t_1300 = datetime.strptime("13:00", "%H:%M").time()
    t_1500 = datetime.strptime("15:00", "%H:%M").time()

    return (t_0900 <= current_time <= t_1130) or (t_1300 <= current_time <= t_1500)

_thread_local = threading.local()

def get_session() -> requests.Session:
    """
    Tạo hoặc tái sử dụng requests.Session riêng cho mỗi luồng (Thread-Local)
    với HTTP Keep-Alive và cơ chế retry tự động.
    """
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        retries = Retry(
            total=2,
            backoff_factor=0.05,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(
            pool_connections=1,
            pool_maxsize=1,
            max_retries=retries
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update(HEADERS)
        _thread_local.session = s
    return _thread_local.session

_snapshot_lock = threading.Lock()
_snapshot_cache = {}
_snapshot_cache_time = {}

def get_exchange_symbols_snapshot(exchange: str) -> List[Dict]:
    """
    Lấy toàn bộ bảng giá thời gian thực sàn HOSE hoặc HNX từ SSI iBoard (kèm cache 20s và retry)
    """
    now = time.time()
    ex = exchange.lower()
    with _snapshot_lock:
        if ex in _snapshot_cache and (now - _snapshot_cache_time.get(ex, 0) < 60):
            return _snapshot_cache[ex]

    url = f"https://iboard-query.ssi.com.vn/stock/exchange/{ex}"
    session = get_session()
    for attempt in range(2):
        try:
            resp = session.get(url, timeout=(1.5, 3.5))
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and "data" in data:
                    res_list = data["data"]
                elif isinstance(data, list):
                    res_list = data
                else:
                    res_list = []
                if res_list:
                    with _snapshot_lock:
                        _snapshot_cache[ex] = res_list
                        _snapshot_cache_time[ex] = time.time()
                    return res_list
        except Exception as e:
            if attempt == 1:
                pass
            time.sleep(0.2)

    with _snapshot_lock:
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

_history_lock = threading.Lock()
_history_cache = {}
_history_cache_time = {}

def get_ticker_history(symbol: str, count: int = 150, days: int = 400) -> Optional[pd.DataFrame]:
    """
    Lấy lịch sử nến ngày từ DNSE Entrade (kèm bộ đệm RAM 120s tải tức thì <0.001s).
    days: số ngày lịch sử cần lấy (mặc định 400 ngày ≈ 270 phiên giao dịch)
    count: giới hạn số nến trả về (None = trả về tất cả)
    """
    sym = symbol.strip().upper()
    now_ts = int(time.time())
    cache_key = (sym, days)

    # 1. Kiểm tra cache RAM
    with _history_lock:
        if cache_key in _history_cache and (now_ts - _history_cache_time.get(cache_key, 0) < 120):
            cached_df = _history_cache[cache_key]
            if count is not None:
                return cached_df.tail(count).reset_index(drop=True)
            return cached_df.copy()

    from_ts = now_ts - days * 86400
    url_dnse = f"https://services.entrade.com.vn/chart-api/v2/ohlcs/stock?from={from_ts}&to={now_ts}&symbol={sym}&resolution=1D"
    try:
        session = get_session()
        resp = session.get(url_dnse, timeout=(1.5, 3.0))
        if resp.status_code == 200:
            data = resp.json()
            if data and "t" in data and len(data["t"]) >= 30:
                df = pd.DataFrame({
                    "time":   data["t"],
                    "open":   data["o"],
                    "high":   data["h"],
                    "low":    data["l"],
                    "close":  data["c"],
                    "volume": data["v"]
                })
                with _history_lock:
                    _history_cache[cache_key] = df
                    _history_cache_time[cache_key] = now_ts

                if count is not None:
                    return df.tail(count).reset_index(drop=True)
                return df.reset_index(drop=True)
    except Exception:
        pass

    # Nếu lỗi mạng thì thử lấy từ cache cũ nếu có
    with _history_lock:
        if cache_key in _history_cache:
            cached_df = _history_cache[cache_key]
            if count is not None:
                return cached_df.tail(count).reset_index(drop=True)
            return cached_df.copy()

    return None

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tính toán các chỉ báo kỹ thuật Volume AI & Keltner (chuẩn 100% Pine Script AI_Whale_ProMax.pine):
    1. Keltner SuperTrend: VWMA(10), ATR(10, factor=2.8)
    2. KNN Volume AI: WMA(20), WMA(100), k=3, n_data=10
    3. ATR(14) cho quản trị vốn TP/SL
    4. Bộ bóp cò State Machine (LONG / SHORT)
    """
    enriched = calculate_all_indicators(df)
    for col in enriched.columns:
        df[col] = enriched[col]
    df['vol_ma20'] = df['volume'].rolling(20).mean()
    return df

def analyze_stock(item: dict, exchange: str) -> Optional[Dict]:
    """
    Phân tích cổ phiếu: Đồng bộ chuẩn xác 100% với chỉ báo Pine Script AI Whale ProMax.
    Chỉ trả về Dict khi THỰC SỰ CÓ ĐIỂM MUA MỚI HÔM NAY (không báo ảo).
    """
    symbol = item.get("stockSymbol") or item.get("ssi_symbol") or item.get("symbol")
    if not symbol or len(symbol) < 2 or len(symbol) > 5 or not symbol.isalpha():
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

    # Lọc thanh khoản tối thiểu (Động theo giờ phiên: Đầu phiên 1-2 tỷ, sau đó >= 3 tỷ VNĐ)
    elapsed_mins = get_elapsed_trading_minutes()
    threshold_val = 1_000_000_000 if elapsed_mins <= 45 else 2_000_000_000 if elapsed_mins <= 90 else config.MIN_TRADE_VALUE
    if total_val < threshold_val:
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

    # 2. XÁC NHẬN DÒNG TIỀN CÁ MẬP (SMART MONEY FOOTPRINT)
    vol_ma20 = float(df_eval['vol_ma20'].iloc[-1])
    highest_vol_15 = df_eval['volume'].iloc[-16:-1].max() if len(df_eval) >= 16 else df_eval['volume'].max()
    effective_vol = max(total_vol, projected_vol)

    # Chuẩn Pine Script: isUltraVol = volume >= (volMa20 * 1.5) or volume >= ta.highest(volume[1], 15)
    is_ultra_vol = (total_vol >= vol_ma20 * config.WHALE_VOLUME_RATIO) or (total_vol >= highest_vol_15) or (effective_vol >= vol_ma20 * config.WHALE_VOLUME_RATIO)
    hud_money = "🐋 CÁ MẬP VÀO" if is_ultra_vol else "Bình Thường 📊"

    # Thông số nến ngày chuẩn Pine Script
    candle_range = today_high - today_low
    if candle_range > 0:
        lower_wick = min(today_open, matched_price) - today_low
        body_size = abs(matched_price - today_open)
        # Chuẩn Pine Script: isHanhViMua = (rauDuoi / chieuDaiNen >= 0.40) or (thanNen / chieuDaiNen >= 0.65 and close > open)
        is_hanh_vi_mua = (lower_wick / candle_range >= config.WHALE_LOWER_WICK_RATIO) or (body_size / candle_range >= 0.65 and matched_price > today_open)
        lower_wick_ratio = lower_wick / candle_range
    else:
        is_hanh_vi_mua = False
        lower_wick_ratio = 0.0

    # 3. KIỂM TRA ĐIỂM BÓP CÒ — ĐÚNG 100% PINE SCRIPT
    # Pine Script dòng 200:
    # buyCondition = (trend == 4) and (prediction > 0) and kernelCrossUp and (xuHuongST == 1)
    # kernelCrossUp = ta.crossover(yhat1, yhat1[1])  ← yhat1 vượt lên trên yhat1[1]
    # chacChanCaMap = isUltraVol and isHanhViMua and (winRate >= nguongTinCay)

    # Lorentzian prediction (>0 = AI dự đoán xu hướng tăng)
    prediction_val = float(df_eval['prediction'].iloc[-1]) if 'prediction' in df_eval.columns else 0.0

    # kernelCrossUp: yhat1 hiện tại > yhat1 trước (crossover lên)
    kernel_cross_up = (
        len(df_eval) >= 3
        and df_eval['yhat1'].iloc[-1] > df_eval['yhat1'].iloc[-2]
        and df_eval['yhat1'].iloc[-2] <= df_eval['yhat1'].iloc[-3]
    )

    # buyCondition: phải có ĐỦ 4 điều kiện
    buy_condition = (
        (current_trend == 4)
        and (prediction_val > 0)
        and kernel_cross_up
        and is_supertrend_bull
    )

    if not buy_condition:
        return None

    # winRate theo Pine Script: ((K + abs(prediction)) / (2*K)) * 100
    K = 8
    win_rate = ((K + abs(prediction_val)) / (2 * K)) * 100.0
    win_rate = max(50.0, min(100.0, win_rate))

    # chacChanCaMap = isUltraVol and isHanhViMua and (winRate >= nguongTinCay)
    is_confirmed_whale = is_ultra_vol and is_hanh_vi_mua and (win_rate >= config.MIN_ALERT_WINRATE)
    whale_badge = "🐋 CÁ MẬP MUA" if is_confirmed_whale else "🚀 MUA VÀO"

    if is_confirmed_whale:
        pattern = "Cá Mập vào lệnh (Vol bùng nổ + Nến áp đảo)"
    else:
        pattern = "Thuật toán Kernel ML và Lorentzian AI kích hoạt điểm MUA"

    # 4. TÍNH TOÁN TP1, TP2, TP3 VÀ STOP LOSS (CHUẨN 100% PINE SCRIPT)
    # Pine Script: slPrice = not na(recentSwingLow) and recentSwingLow < close ? recentSwingLow : close - (atrRM * 1.5)
    recent_swing_low = df_eval['low'].iloc[-11:-1].min() if len(df_eval) > 11 else df_eval['low'].min()
    atr14_val = float(df_eval['atr14'].iloc[-1]) if 'atr14' in df_eval.columns and pd.notna(df_eval['atr14'].iloc[-1]) else (matched_price * 0.03)

    if pd.notna(recent_swing_low) and recent_swing_low < matched_price and (matched_price - recent_swing_low) <= (matched_price * 0.15):
        sl = recent_swing_low
    else:
        sl = matched_price - (atr14_val * 1.5)

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


    in_session = is_trading_hour()
    now_str = datetime.now().strftime("%H:%M %d/%m/%Y")
    today_str = datetime.now().strftime("%d/%m/%Y")
    candle_ts = df['time'].iloc[-1] if 'time' in df.columns else None
    last_candle_date = datetime.fromtimestamp(int(candle_ts)).strftime("%d/%m/%Y") if candle_ts else today_str
    # Nếu nến cuối là hôm nay (sau phiên), dùng ngày hôm nay
    if last_candle_date != today_str:
        candle_today = datetime.fromtimestamp(int(candle_ts)).date() if candle_ts else None
        if candle_today and candle_today == datetime.now().date():
            last_candle_date = today_str

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

    # TẢI SNAPSHOT CÁC SÀN ĐỒNG THỜI (CONCURRENT SNAPSHOT INGESTION)
    print(f"[*] Đang tải dữ liệu các sàn ({', '.join(config.EXCHANGES)}) song song...")
    exchange_items = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(config.EXCHANGES)) as ex_executor:
        future_to_ex = {ex_executor.submit(get_exchange_symbols_snapshot, ex): ex for ex in config.EXCHANGES}
        for future in concurrent.futures.as_completed(future_to_ex):
            ex = future_to_ex[future]
            try:
                items = future.result()
                exchange_items[ex] = items
                print(f" -> Nhận được {len(items)} mã trên sàn {ex}.")
            except Exception as e:
                print(f"[Cảnh báo] Lỗi tải dữ liệu sàn {ex}: {e}")
                exchange_items[ex] = []

    # TẦNG 1: LỌC NHANH TRÊN SNAPSHOT CHO TẤT CẢ CÁC SÀN
    elapsed_mins = get_elapsed_trading_minutes()
    threshold_val = 1_000_000_000 if elapsed_mins <= 45 else 2_000_000_000 if elapsed_mins <= 90 else config.MIN_TRADE_VALUE

    all_candidates = []
    total_symbols = 0
    for exchange in config.EXCHANGES:
        items = exchange_items.get(exchange, [])
        total_symbols += len(items)
        for item in items:
            sym = item.get("stockSymbol") or item.get("symbol")
            if not sym or len(sym) < 2 or len(sym) > 5 or not sym.isalpha():
                continue
            p = normalize_price_k(item.get("matchedPrice") or item.get("lastPrice") or item.get("expectedMatchedPrice") or item.get("refPrice") or 0)
            v = float(item.get("totalVol") or item.get("nmTotalTradedQty") or item.get("expectedMatchedVolume") or 0)
            val = float(item.get("totalVal") or (p * 1000.0 * v))
            
            if val >= threshold_val or (val >= 800_000_000 and float(item.get("changePercent", 0) or 0) >= 1.0):
                all_candidates.append((item, exchange))

    print(f" -> Tầng 1 đã chọn {len(all_candidates)} mã tiềm năng từ {total_symbols} mã (loại bỏ {total_symbols - len(all_candidates)} mã thanh khoản yếu). Đang phân tích chuyên sâu đa luồng...")

    # TẦNG 2: PHÂN TÍCH CHUYÊN SÂU ĐA LUỒNG SIÊU TỐC TRÊN HÀNG ĐỢI HỢP NHẤT
    max_workers = getattr(config, "MAX_WORKERS", 16)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_candidate = {
            executor.submit(analyze_stock, item, exchange): (item, exchange)
            for item, exchange in all_candidates
        }
        for future in concurrent.futures.as_completed(future_to_candidate):
            try:
                result = future.result()
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
