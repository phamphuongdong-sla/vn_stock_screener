# -*- coding: utf-8 -*-
"""
fmab_indicators.py — Động cơ tính toán chỉ báo [blackcat] L1 Fibonacci MA Band (FMAB)
Đồng bộ 100% với Pine Script v6:
  - Whale MA (Fast EMA 13): Đường cá mập dẫn dắt dòng tiền ngắn hạn
  - Resistance MA (Slow EMA 144): Đường cản Fibonacci lớn 144
  - Linreg Slope (Length 21, Multiplier 23.0)
  - Trendline MA (EMA 50 của nguồn độ dốc): Đường xu hướng tổng thể
  - Quản trị tín hiệu: Exclusivity (loại bỏ nhiễu cùng thanh) & Cooldown (3 nến)
  - Quản trị rủi ro ATR 14: Stop Loss (2.0x ATR) & Take Profit (3.0x ATR)
  - Tối ưu cho TTCK Việt Nam (Long-only cho cổ phiếu cơ sở, hỗ trợ 2 chiều cho phái sinh)
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, Tuple


def pine_linreg_fast(series: pd.Series, length: int) -> pd.Series:
    """
    Tính đường hồi quy tuyến tính ta.linreg(src, length, 0)
    Sử dụng tích chập (Convolution) tối ưu hiệu năng O(N), nhanh hơn rolling.apply gấp 1000 lần.
    """
    n = len(series)
    if n < length:
        return pd.Series(np.nan, index=series.index)

    x = np.arange(length)
    x_mean = (length - 1) / 2.0
    x_var = np.sum((x - x_mean) ** 2)
    weights = (x - x_mean) / x_var

    # Tích chập tính độ dốc
    vals = series.values.astype(float)
    slope_raw = np.convolve(vals, weights[::-1], mode='full')[:n]
    slope_raw[:length - 1] = np.nan

    # Trung bình trượt
    rolling_mean = series.rolling(length).mean().values

    # Giá trị hồi quy tại thanh hiện tại: intercept + slope * (length - 1) = mean + slope * (length - 1)/2
    linreg = rolling_mean + slope_raw * ((length - 1) / 2.0)
    return pd.Series(linreg, index=series.index)


def compute_fmab(
    df: pd.DataFrame,
    whale_len: int = 13,
    res_len: int = 144,
    slope_len: int = 21,
    slope_mult: float = 23.0,
    trend_len: int = 50,
    atr_len: int = 14,
    use_exclusivity: bool = True,
    cooldown_bars: int = 3,
    sl_mult: float = 2.0,
    tp_mult: float = 3.0,
    is_long_only: bool = True
) -> Dict[str, Any]:
    """
    Tính toán toàn bộ hệ thống chỉ báo FMAB và máy trạng thái cho chuỗi nến OHLCV.
    """
    if df is None or len(df) < max(whale_len, res_len, slope_len, trend_len, 30):
        return {}

    close = df['close'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    volume = df['volume'].astype(float) if 'volume' in df.columns else pd.Series(0.0, index=close.index)
    n = len(df)

    # 1. Whale MA (EMA 13)
    whale_ma = close.ewm(span=whale_len, adjust=False).mean()

    # 2. Resistance MA (EMA 144)
    res_ma = close.ewm(span=res_len, adjust=False).mean()

    # 3. Slope Regression 21
    linreg_s = pine_linreg_fast(close, slope_len)
    slope = linreg_s.diff()
    if len(slope) > 0:
        slope.iloc[0] = 0.0
    slope = slope.fillna(0.0)

    # 4. Trendline MA (EMA 50 của slope * slope_mult + close)
    trend_src = slope * slope_mult + close
    trendline_ma = trend_src.ewm(span=trend_len, adjust=False).mean()

    # 5. ATR (Wilder's smoothing)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / atr_len, adjust=False).mean()

    # 6. Máy trạng thái (State Machine)
    pos_state = [0] * n
    last_sig_bar = None
    entry_prices = [np.nan] * n
    entry_dirs = [0] * n
    long_entries = [False] * n
    short_entries = [False] * n
    long_exits = [False] * n
    short_exits = [False] * n

    c_vals = close.values
    w_vals = whale_ma.values

    for i in range(1, n):
        c_curr = c_vals[i]
        c_prev = c_vals[i - 1]
        w_curr = w_vals[i]
        w_prev = w_vals[i - 1]

        # Crossover / Crossunder
        long_entry_cond = (c_prev <= w_prev) and (c_curr > w_curr)
        short_entry_cond = (c_prev >= w_prev) and (c_curr < w_curr)
        long_exit_cond = short_entry_cond
        short_exit_cond = long_entry_cond

        cur_pos = pos_state[i - 1]
        cooldown_ok = (last_sig_bar is None) or (cooldown_bars == 0) or ((i - last_sig_bar) > cooldown_bars)

        raw_long_entry = long_entry_cond and (cur_pos <= 0) and cooldown_ok
        raw_short_entry = short_entry_cond and (cur_pos >= 0) and cooldown_ok
        raw_long_exit = long_exit_cond and (cur_pos == 1)
        raw_short_exit = short_exit_cond and (cur_pos == -1)

        if use_exclusivity:
            l_exit = raw_long_exit and (not raw_long_entry) and (not raw_short_entry)
            s_exit = raw_short_exit and (not raw_long_entry) and (not raw_short_entry)
            l_entry = raw_long_entry and (not l_exit) and (not s_exit)
            s_entry = raw_short_entry and (not l_exit) and (not s_exit)
        else:
            l_exit = raw_long_exit
            s_exit = raw_short_exit
            l_entry = raw_long_entry
            s_entry = raw_short_entry

        long_entries[i] = l_entry
        short_entries[i] = s_entry
        long_exits[i] = l_exit
        short_exits[i] = s_exit

        if is_long_only:
            # Thị trường cơ sở VN: shortEntry hoặc longExit chuyển về trạng thái Tiền mặt (posState = 0)
            if l_entry:
                pos_state[i] = 1
                last_sig_bar = i
                entry_prices[i] = c_curr
                entry_dirs[i] = 1
            elif s_entry or l_exit:
                pos_state[i] = 0
                last_sig_bar = i
                entry_prices[i] = np.nan
                entry_dirs[i] = 0
            else:
                pos_state[i] = cur_pos
                entry_prices[i] = entry_prices[i - 1]
                entry_dirs[i] = entry_dirs[i - 1]
        else:
            # Thị trường phái sinh 2 chiều
            if l_entry:
                pos_state[i] = 1
                last_sig_bar = i
                entry_prices[i] = c_curr
                entry_dirs[i] = 1
            elif s_entry:
                pos_state[i] = -1
                last_sig_bar = i
                entry_prices[i] = c_curr
                entry_dirs[i] = -1
            elif l_exit or s_exit:
                pos_state[i] = 0
                last_sig_bar = i
                entry_prices[i] = np.nan
                entry_dirs[i] = 0
            else:
                pos_state[i] = cur_pos
                entry_prices[i] = entry_prices[i - 1]
                entry_dirs[i] = entry_dirs[i - 1]

    # Thanh mới nhất
    last_idx = n - 1
    curr_c = float(c_vals[last_idx])
    prev_c = float(c_vals[last_idx - 1]) if last_idx > 0 else curr_c
    curr_w = float(w_vals[last_idx])
    curr_r = float(res_ma.iloc[last_idx])
    curr_t = float(trendline_ma.iloc[last_idx])
    curr_atr = float(atr.iloc[last_idx])
    curr_slope = float(slope.iloc[last_idx])

    curr_pos = pos_state[last_idx]
    has_buy_signal = bool(long_entries[last_idx])
    has_sell_signal = bool(short_entries[last_idx])
    has_exit_signal = bool(long_exits[last_idx])

    entry_p = entry_prices[last_idx]
    entry_d = entry_dirs[last_idx]

    # Tính TP / SL theo chuẩn tác giả blackcat1402 (TradingView: OZhERgT3)
    sl_price = np.nan
    tp_price = np.nan
    sl_pct = 0.0
    tp_pct = 0.0

    ref_entry = entry_p if not np.isnan(entry_p) else (curr_c if has_buy_signal else np.nan)
    ref_dir = entry_d if entry_d != 0 else (1 if has_buy_signal else 0)

    if not np.isnan(ref_entry) and ref_dir != 0 and curr_atr > 0:
        sl_price = ref_entry - ref_dir * sl_mult * curr_atr
        tp_price = ref_entry + ref_dir * tp_mult * curr_atr
        sl_pct = ((sl_price / ref_entry) - 1.0) * 100.0
        tp_pct = ((tp_price / ref_entry) - 1.0) * 100.0

    # Kế hoạch giao dịch dự kiến (Kể cả khi đang Flat chờ điểm kích hoạt bứt phá)
    if curr_pos == 1:
        plan_entry_price = ref_entry
        plan_sl_price = sl_price
        plan_tp_price = tp_price
        plan_sl_pct = sl_pct
        plan_tp_pct = tp_pct
    elif has_buy_signal:
        plan_entry_price = curr_c
        plan_sl_price = curr_c - sl_mult * curr_atr
        plan_tp_price = curr_c + tp_mult * curr_atr
        plan_sl_pct = ((plan_sl_price / curr_c) - 1.0) * 100.0
        plan_tp_pct = ((plan_tp_price / curr_c) - 1.0) * 100.0
    else:
        # Nếu đang Flat: Điểm vào dự kiến là vùng bứt phá Whale MA (hoặc giá hiện tại)
        plan_entry_price = curr_w if curr_c < curr_w else curr_c
        plan_sl_price = plan_entry_price - sl_mult * curr_atr
        plan_tp_price = plan_entry_price + tp_mult * curr_atr
        plan_sl_pct = ((plan_sl_price / plan_entry_price) - 1.0) * 100.0
        plan_tp_pct = ((plan_tp_price / plan_entry_price) - 1.0) * 100.0

    # Trạng thái Dải (Bands) & Xu hướng
    is_bull_band = curr_w > curr_r
    is_bull_trend = curr_c >= curr_t
    band_name = "BULL BAND 🐂 (Dải Xanh)" if is_bull_band else "BEAR BAND 🐻 (Dải Đỏ)"
    trend_name = "UPTREND 📈 (Nến trên Trendline)" if is_bull_trend else "DOWNTREND 📉 (Nến dưới Trendline)"

    # Khối lượng so với MA20
    vol_ma20 = float(volume.rolling(20).mean().iloc[last_idx]) if len(volume) >= 20 else float(volume.mean())
    curr_vol = float(volume.iloc[last_idx])
    vol_ratio = (curr_vol / vol_ma20) if vol_ma20 > 0 else 1.0

    # Chấm điểm hợp lưu (Confluence Score: 0 - 3 sao)
    confluence_score = 0
    if has_buy_signal or curr_pos == 1:
        confluence_score += 1
    if is_bull_band:
        confluence_score += 1
    if is_bull_trend:
        confluence_score += 1

    if confluence_score == 3:
        confluence_tag = "⭐⭐⭐ SIÊU HỢP LƯU (Trend + Band + Signal)"
    elif confluence_score == 2:
        confluence_tag = "⭐⭐ HỢP LƯU TỐT (Đạt 2/3 điều kiện)"
    elif confluence_score == 1:
        confluence_tag = "⭐ TÍN HIỆU SỚM (1/3 điều kiện)"
    else:
        confluence_tag = "⚪ XU HƯỚNG YẾU (Dưới cản)"

    # Đánh giá hành động đề xuất
    profit_pct = ((curr_c / ref_entry) - 1.0) * 100.0 if not np.isnan(ref_entry) else 0.0
    if has_buy_signal:
        action_title = "🟢 KÍCH HOẠT ĐIỂM MUA (BUY ENTRY)"
        action_detail = f"Giá ({curr_c:.2f}) vừa cắt lên trên Whale MA ({curr_w:.2f})."
    elif is_long_only and (has_sell_signal or has_exit_signal):
        action_title = "🔴 KÍCH HOẠT BÁN THOÁT HÀNG (EXIT)"
        action_detail = f"Giá ({curr_c:.2f}) vừa thủng xuống dưới Whale MA ({curr_w:.2f})."
    elif curr_pos == 1:
        action_title = f"🟢 ĐANG NẮM GIỮ (LONG: {profit_pct:+.2f}%)"
        action_detail = f"Vị thế Long từ vùng giá {ref_entry:.2f}."
    else:
        action_title = "⚪ TIỀN MẶT / QUAN SÁT (CASH)"
        action_detail = f"Chờ giá bứt phá vượt qua Whale MA ({curr_w:.2f}) để kích hoạt điểm MUA."

    return {
        'price': curr_c,
        'change_pct': ((curr_c / prev_c) - 1.0) * 100.0 if prev_c > 0 else 0.0,
        'volume': curr_vol,
        'vol_ma20': vol_ma20,
        'vol_ratio': vol_ratio,
        'whale_ma': curr_w,
        'res_ma': curr_r,
        'trendline_ma': curr_t,
        'atr': curr_atr,
        'slope': curr_slope,
        'pos_state': curr_pos,
        'has_buy_signal': has_buy_signal,
        'has_sell_signal': has_sell_signal,
        'has_exit_signal': has_exit_signal,
        'is_bull_band': is_bull_band,
        'is_bull_trend': is_bull_trend,
        'band_name': band_name,
        'trend_name': trend_name,
        'confluence_score': confluence_score,
        'confluence_tag': confluence_tag,
        'action_title': action_title,
        'action_detail': action_detail,
        'entry_price': ref_entry,
        'sl_price': sl_price,
        'tp_price': tp_price,
        'sl_pct': sl_pct,
        'tp_pct': tp_pct,
        'plan_entry_price': plan_entry_price,
        'plan_sl_price': plan_sl_price,
        'plan_tp_price': plan_tp_price,
        'plan_sl_pct': plan_sl_pct,
        'plan_tp_pct': plan_tp_pct,
        'profit_pct': profit_pct,
        'ma_exit_price': curr_w,
        'rr_ratio': 1.5,
    }
