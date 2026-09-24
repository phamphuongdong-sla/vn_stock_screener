# -*- coding: utf-8 -*-
"""
dtpro_indicators.py — Port 100% Pine Script:
"DÒNG TIỀN & XU HƯỚNG PRO - MASTER EDITION"

Thành phần chính:
  1. Nadaraya-Watson Gaussian Regression (Non-Repaint, 500-bar kernel)
  2. Keltner SuperTrend (EMA hlc3, ATR 14, factor 2.8)
  3. MTF Confirmation: Daily (D) & Weekly (W)
  4. Signal: buyDiamond / buyStandard / sellDiamond / sellStandard
  5. Risk: SL, TP1, TP2 theo ATR × 1.5
"""

import numpy as np
import pandas as pd
from typing import Optional, Dict, Tuple
from datetime import datetime, timedelta


# ─────────────────────────────────────────────
# 1. NADARAYA-WATSON GAUSSIAN REGRESSION
# ─────────────────────────────────────────────

def _gauss_weights(window: int, h: float) -> np.ndarray:
    """Precompute Gaussian kernel weights (distance 0..window-1)."""
    i = np.arange(window, dtype=np.float64)
    return np.exp(-(i ** 2) / (h * h * 2))


def calc_nadaraya_watson(
    close: pd.Series,
    h: float = 8.0,
    window: int = 500,
) -> pd.Series:
    """
    One-sided Gaussian kernel NW estimator — non-repainting.
    Tối ưu hóa C-level 1D convolution (nhanh hơn 20x so với vòng lặp).

    Pine Script equivalent:
        gaussKernel(x, h) = exp(-(x² / (h² * 2)))
        coefs[i] = gaussKernel(i, h)  for i in 0..499
        nwOut = sum(close[i] * coefs[i]) / sum(coefs)
    """
    vals = close.values.astype(np.float64)
    n = len(vals)
    w_len = min(window, n)
    weights = _gauss_weights(w_len, h)

    # Chuẩn hóa mẫu số động theo số nến quá khứ có sẵn
    denoms = np.empty(n, dtype=np.float64)
    denoms[:w_len] = np.cumsum(weights)
    if n > w_len:
        denoms[w_len:] = weights.sum()

    conv = np.convolve(vals, weights, mode='full')[:n]
    result = conv / denoms

    return pd.Series(result, index=close.index)


def calc_nw_bands(
    close: pd.Series,
    nw_out: pd.Series,
    nw_mult: float = 3.0,
    mae_window: int = 499,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Pine: nwMae = ta.sma(abs(close - nwOut), 499) * nwMult
          nwUpper = nwOut + nwMae
          nwLower = nwOut - nwMae
    """
    abs_dev = (close - nw_out).abs()
    nw_mae  = abs_dev.rolling(mae_window, min_periods=max(1, mae_window // 5)).mean() * nw_mult
    upper   = nw_out + nw_mae
    lower   = nw_out - nw_mae
    return nw_out, upper, lower


# ─────────────────────────────────────────────
# 2. ATR & SUPERTREND (KELTNER)
# ─────────────────────────────────────────────

def calc_atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high = df['high']; low = df['low']; prev_close = df['close'].shift(1)
    tr = pd.concat([high - low,
                    (high - prev_close).abs(),
                    (low  - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False).mean()


def calc_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def calc_supertrend(
    df: pd.DataFrame,
    st_len: int = 10,
    atr_mult: float = 2.8,
    atr_len: int = 14,
) -> Tuple[pd.Series, pd.Series]:
    """
    Keltner SuperTrend: basis = EMA(hlc3, stLen), bands ± mult*ATR
    Same ratchet mechanism as GDNL.
    Returns: (direction: 1=bull/-1=bear, st_line)
    """
    hlc3  = (df['high'] + df['low'] + df['close']) / 3.0
    atr   = calc_atr(df, atr_len)
    basis = calc_ema(hlc3, st_len)

    ub_basic = (basis + atr_mult * atr).values
    lb_basic = (basis - atr_mult * atr).values
    close    = df['close'].values
    n        = len(close)

    upper_final = np.full(n, np.nan)
    lower_final = np.full(n, np.nan)
    direction   = np.ones(n, dtype=int)

    for i in range(n):
        if i == 0:
            upper_final[i] = ub_basic[i]
            lower_final[i] = lb_basic[i]
        else:
            # upper ratchet
            upper_final[i] = (ub_basic[i]
                              if ub_basic[i] < upper_final[i-1] or close[i-1] > upper_final[i-1]
                              else upper_final[i-1])
            # lower ratchet
            lower_final[i] = (lb_basic[i]
                              if lb_basic[i] > lower_final[i-1] or close[i-1] < lower_final[i-1]
                              else lower_final[i-1])
            # direction
            prev = direction[i-1]
            if prev == -1 and close[i] > upper_final[i-1]:
                direction[i] = 1
            elif prev == 1 and close[i] < lower_final[i-1]:
                direction[i] = -1
            else:
                direction[i] = prev

    st_line = np.where(direction == 1, lower_final, upper_final)
    return (pd.Series(direction, index=df.index),
            pd.Series(st_line,  index=df.index))


# ─────────────────────────────────────────────
# 3. MTF STATE (DAILY & WEEKLY)
# ─────────────────────────────────────────────

def _ema_state(close: pd.Series, fast: int = 20, slow: int = 50) -> int:
    """
    Pine f_mtfScan():
      f = EMA(close, emaFast); s = EMA(close, emaSlow)
      close > f and f > s → 1
      close < f and f < s → -1
      else 0
    """
    if len(close) < slow + 5:
        return 0
    f = calc_ema(close, fast).iloc[-1]
    s = calc_ema(close, slow).iloc[-1]
    c = float(close.iloc[-1])
    if c > f and f > s:
        return 1
    if c < f and f < s:
        return -1
    return 0


def calc_mtf_states(
    df: pd.DataFrame,
    ema_fast: int = 20,
    ema_slow: int = 50,
) -> Tuple[int, int]:
    """
    Daily state  = MTF state of the daily df itself (EMA20/50 on daily close)
    Weekly state = MTF state on weekly-resampled close
    Returns: (state_D, state_W)
    NOTE: Weekly resampling uses only fully-closed weeks to avoid look-ahead bias.
    """
    # Daily: use full df (tất cả nến ngày đã đóng — nến hiện tại chưa đóng
    # không được ghép vào df này trong flow chính)
    state_d = _ema_state(df['close'], ema_fast, ema_slow)

    # Weekly: resample daily → weekly close (last close of each completed week)
    try:
        df_ts = df.copy()
        df_ts['date'] = pd.to_datetime(df_ts['time'], unit='s', utc=True).dt.tz_convert('Asia/Ho_Chi_Minh')
        df_ts = df_ts.set_index('date')
        weekly_close = df_ts['close'].resample('W').last().dropna()

        # Loại bỏ tuần hiện tại nếu chưa kết thúc (tránh look-ahead bias)
        from datetime import datetime
        import pytz
        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        now = datetime.now(vn_tz)
        # Tuần kết thúc vào Chủ Nhật — nếu hôm nay chưa phải CN thì tuần cuối chưa đóng
        if now.weekday() < 6:  # 6 = Sunday
            weekly_close = weekly_close.iloc[:-1]

        if len(weekly_close) >= ema_slow:
            state_w = _ema_state(weekly_close, ema_fast, ema_slow)
        else:
            state_w = state_d   # fallback nếu không đủ dữ liệu tuần
    except Exception:
        state_w = 0

    return state_d, state_w


# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# 4. SIGNAL & POSITION TRACKING (PINE SCRIPT STATE MACHINE)
# ─────────────────────────────────────────────

def track_positions_and_signals(
    df: pd.DataFrame,
    direction: pd.Series,
    nw_upper: pd.Series,
    nw_lower: pd.Series,
    atr_series: pd.Series,
    cua_so_lookback: int = 7,
    rr1: float = 1.0,
    rr2: float = 2.0,
    vni_trend_map: dict = None,
) -> Dict:
    """
    Mô phỏng 100% logic Pine Script DÒNG TIỀN & XU HƯỚNG PRO:
      isVungDayNW  = low <= nwLower or nwCrossDown
      isVungDinhNW = high >= nwUpper or nwCrossUp
      barsSinceNWLow  = ta.barssince(isVungDayNW)
      hadNWLow  = barsSinceNWLow <= cuaSoLookback
      buyDiamond  = buyTrigger and hadNWLow
      buyStandard = buyTrigger and not hadNWLow
      activePos, posName, entryP, slP, tp1P, tp2P, pnlPct
    """
    close = df['close'].values
    high  = df['high'].values
    low   = df['low'].values
    dirs  = direction.values
    nw_u  = nw_upper.values
    nw_l  = nw_lower.values
    atr_v = atr_series.values
    t_arr = df['time'].values if 'time' in df.columns else np.zeros(len(close), dtype=int)
    n = len(close)

    # 1. Tính isVungDayNW và isVungDinhNW trên từng nến
    is_day_nw = np.zeros(n, dtype=bool)
    is_dinh_nw = np.zeros(n, dtype=bool)

    for i in range(1, n):
        cross_down = (close[i-1] >= nw_l[i-1]) and (close[i] < nw_l[i])
        cross_up   = (close[i-1] <= nw_u[i-1]) and (close[i] > nw_u[i])
        is_day_nw[i]  = (low[i] <= nw_l[i]) or cross_down
        is_dinh_nw[i] = (high[i] >= nw_u[i]) or cross_up

    # 2. State Machine: Duyệt qua lịch sử để xác định activePos, entryP, slP, tp1P, tp2P
    active_pos = 0
    pos_name = "ĐANG QUAN SÁT"
    entry_p = 0.0
    sl_p = 0.0
    tp1_p = 0.0
    tp2_p = 0.0
    last_trigger_bar = -1
    last_trigger_type = ""

    last_nw_low_bar = -9999
    last_nw_high_bar = -9999

    buy_trades = []
    sell_trades = []

    for i in range(1, n):
        if is_day_nw[i]:
            last_nw_low_bar = i
        if is_dinh_nw[i]:
            last_nw_high_bar = i

        buy_trigger  = (dirs[i] == 1 and dirs[i-1] == -1)
        sell_trigger = (dirs[i] == -1 and dirs[i-1] == 1)

        had_nw_low  = (i - last_nw_low_bar) <= cua_so_lookback
        had_nw_high = (i - last_nw_high_bar) <= cua_so_lookback

        if buy_trigger:
            active_pos = 1
            is_diamond = had_nw_low
            pos_name = "💎 MUA MẠNH" if is_diamond else "MUA"
            entry_p = close[i]
            sl_p = close[i] - atr_v[i] * 1.5
            r = abs(entry_p - sl_p)
            tp1_p = close[i] + r * rr1
            tp2_p = close[i] + r * rr2
            last_trigger_bar = i
            last_trigger_type = "BUY_DIAMOND" if is_diamond else "BUY_STANDARD"
            vni_up = vni_trend_map.get(t_arr[i], True) if vni_trend_map else True
            buy_trades.append({
                'bar': i,
                'is_diamond': is_diamond,
                'entry': entry_p,
                'sl': sl_p,
                'tp1': tp1_p,
                'tp2': tp2_p,
                'vni_up': vni_up,
                'time': t_arr[i],
            })

        elif sell_trigger:
            active_pos = -1
            is_diamond = had_nw_high
            pos_name = "🔥 BÁN MẠNH" if is_diamond else "BÁN"
            entry_p = close[i]
            sl_p = close[i] + atr_v[i] * 1.5
            r = abs(entry_p - sl_p)
            tp1_p = close[i] - r * rr1
            tp2_p = close[i] - r * rr2
            last_trigger_bar = i
            last_trigger_type = "SELL_DIAMOND" if is_diamond else "SELL_STANDARD"
            sell_trades.append({
                'bar': i,
                'is_diamond': is_diamond
            })

    # Trạng thái nến hiện tại (phiên hôm nay)
    curr_buy_trigger  = (dirs[-1] == 1 and dirs[-2] == -1) if n >= 2 else False
    curr_sell_trigger = (dirs[-1] == -1 and dirs[-2] == 1) if n >= 2 else False
    curr_had_nw_low   = (n - 1 - last_nw_low_bar) <= cua_so_lookback
    curr_had_nw_high  = (n - 1 - last_nw_high_bar) <= cua_so_lookback

    buy_diamond   = curr_buy_trigger and curr_had_nw_low
    buy_standard  = curr_buy_trigger and not curr_had_nw_low
    sell_diamond  = curr_sell_trigger and curr_had_nw_high
    sell_standard = curr_sell_trigger and not curr_had_nw_high

    # Vùng NW nến hiện tại
    c_cur = close[-1]
    l_cur = low[-1]
    h_cur = high[-1]
    nw_l_cur = nw_l[-1]
    nw_u_cur = nw_u[-1]

    in_day_nw  = (l_cur <= nw_l_cur) or (c_cur <= nw_l_cur)
    in_dinh_nw = (h_cur >= nw_u_cur) or (c_cur >= nw_u_cur)
    nw_zone_label = "VÙNG ĐÁY" if in_day_nw else ("VÙNG ĐỈNH" if in_dinh_nw else "TRUNG TÍNH")

    # Tính PnL % theo vị thế đang giữ
    if entry_p > 0 and active_pos != 0:
        pnl_pct = ((close[-1] - entry_p) / entry_p) * 100.0 * active_pos
        str_pos = f"{pos_name} ({'+' if pnl_pct >= 0 else ''}{pnl_pct:.2f}%)"
    else:
        pnl_pct = 0.0
        str_pos = pos_name

    # Mô tả tín hiệu
    if buy_diamond:
        signal_str = "💎 MUA MẠNH (Hợp lưu Đáy NW + Đảo chiều SuperTrend)"
        has_signal = True
    elif buy_standard:
        signal_str = "🟢 MUA (SuperTrend Đảo Chiều Tăng)"
        has_signal = True
    elif sell_diamond:
        signal_str = "🔥 BÁN MẠNH (Hợp lưu Đỉnh NW + Đảo chiều SuperTrend)"
        has_signal = True
    elif sell_standard:
        signal_str = "🔴 BÁN (SuperTrend Đảo Chiều Giảm)"
        has_signal = True
    else:
        signal_str = "⏸ ĐANG QUAN SÁT"
        has_signal = False

    bars_since_trigger = (n - 1 - last_trigger_bar) if last_trigger_bar >= 0 else 999
    bars_since_nw_low   = (n - 1 - last_nw_low_bar) if last_nw_low_bar >= 0 else 999
    bars_since_nw_high  = (n - 1 - last_nw_high_bar) if last_nw_high_bar >= 0 else 999

    # Thống kê hiệu quả toàn bộ các lệnh Mua lịch sử của mã (Backtest)
    buy_stats_list = []
    for bt in buy_trades:
        b_bar = bt['bar']
        b_entry = bt['entry']
        b_sl = bt['sl']
        b_tp1 = bt['tp1']
        b_tp2 = bt['tp2']
        b_dia = bt['is_diamond']

        first_tp1 = None
        first_tp2 = None
        first_sl = None

        for j in range(b_bar + 1, n):
            if first_sl is None and low[j] <= b_sl:
                first_sl = j
            if first_tp1 is None and high[j] >= b_tp1:
                first_tp1 = j
            if first_tp2 is None and high[j] >= b_tp2:
                first_tp2 = j
            if dirs[j] == -1 and dirs[j-1] == 1:
                break

        win_tp1 = (first_tp1 is not None) and (first_sl is None or first_tp1 < first_sl)
        win_tp2 = (first_tp2 is not None) and (first_sl is None or first_tp2 < first_sl)
        hit_sl_first = (first_sl is not None) and (first_tp1 is None or first_sl < first_tp1)

        # Tính VN-Index win/loss
        b_vni_up = bt.get('vni_up', True)
        trend_end_bar = n - 1
        if vni_trend_map:
            for j in range(b_bar + 1, n):
                cur_vni_up = vni_trend_map.get(t_arr[j])
                if cur_vni_up is not None and cur_vni_up != b_vni_up:
                    trend_end_bar = j
                    break
        
        gia_cuoi = close[trend_end_bar]
        if b_vni_up:
            vni_trend_win = gia_cuoi > b_entry
        else:
            vni_trend_win = gia_cuoi < b_entry

        buy_stats_list.append({
            'is_diamond': b_dia,
            'vni_up': b_vni_up,
            'vni_trend_win': vni_trend_win,
            'gia_dau': b_entry,
            'gia_cuoi': gia_cuoi,
        })

    # Tổng hợp các tín hiệu
    tot_buys = len(buy_stats_list)
    dia_list = [t for t in buy_stats_list if t['is_diamond']]
    std_list = [t for t in buy_stats_list if not t['is_diamond']]
    
    n_buy_diamond = len(dia_list)
    n_buy = len(std_list)
    
    tot_signals = tot_buys + len(sell_trades)
    buy_ratio = round(tot_buys / tot_signals * 100.0, 2) if tot_signals else 0.0

    vni_up_list = [t for t in buy_stats_list if t['vni_up']]
    vni_dn_list = [t for t in buy_stats_list if not t['vni_up']]
    
    vni_up_wins = sum(1 for t in vni_up_list if t['vni_trend_win'])
    vni_dn_wins = sum(1 for t in vni_dn_list if t['vni_trend_win'])
    tot_wins = sum(1 for t in buy_stats_list if t['vni_trend_win'])
    
    buy_stats = {
        'n_buy': n_buy,
        'n_buy_diamond': n_buy_diamond,
        'total_buys': tot_buys,
        'total_signals': tot_signals,
        'buy_ratio': buy_ratio,
        
        'vni_up_cnt': len(vni_up_list),
        'vni_up_wins': vni_up_wins,
        'vni_up_winrate': round(vni_up_wins / len(vni_up_list) * 100.0, 2) if vni_up_list else 0.0,
        
        'vni_dn_cnt': len(vni_dn_list),
        'vni_dn_wins': vni_dn_wins,
        'vni_dn_winrate': round(vni_dn_wins / len(vni_dn_list) * 100.0, 2) if vni_dn_list else 0.0,
        
        'tot_wins': tot_wins,
        'tot_winrate': round(tot_wins / tot_buys * 100.0, 2) if tot_buys else 0.0,
    }

    return {
        'buy_trigger':        curr_buy_trigger,
        'sell_trigger':       curr_sell_trigger,
        'buy_diamond':        buy_diamond,
        'buy_standard':       buy_standard,
        'sell_diamond':       sell_diamond,
        'sell_standard':      sell_standard,
        'has_signal':         has_signal,
        'is_buy':             curr_buy_trigger,
        'is_sell':            curr_sell_trigger,
        'signal_str':         signal_str,
        'nw_zone_label':      nw_zone_label,
        'in_day_nw':          in_day_nw,
        'in_dinh_nw':         in_dinh_nw,
        'nw_upper':           float(nw_u_cur),
        'nw_lower':           float(nw_l_cur),
        'direction':          int(dirs[-1]),
        'active_pos':         active_pos,
        'pos_name':           pos_name,
        'str_pos':            str_pos,
        'entry_p':            entry_p,
        'sl_p':               sl_p,
        'tp1_p':              tp1_p,
        'tp2_p':              tp2_p,
        'pnl_pct':            pnl_pct,
        'bars_since_trigger': bars_since_trigger,
        'bars_since_nw_low':  bars_since_nw_low,
        'bars_since_nw_high': bars_since_nw_high,
        'had_nw_low':         curr_had_nw_low,
        'had_nw_high':        curr_had_nw_high,
        'last_vni_up':        buy_trades[-1]['vni_up'] if buy_trades else True,
        'buy_stats':          buy_stats,
    }


# ─────────────────────────────────────────────
# 5. HÀM TỔNG HỢP: ANALYZE_DTPRO
# ─────────────────────────────────────────────

def analyze_dtpro(
    df: pd.DataFrame,
    symbol: str = "",
    exchange: str = "",
    live_price: float = 0.0,
    live_high:  float = 0.0,
    live_low:   float = 0.0,
    live_vol:   float = 0.0,
    change_pct: float = 0.0,
    # Params Pine Script
    st_len:          int   = 10,
    atr_len:         int   = 14,
    st_mult:         float = 2.8,
    ema_fast:        int   = 20,
    ema_slow:        int   = 50,
    nw_h:            float = 8.0,
    nw_mult:         float = 3.0,
    nw_win:          int   = 500,
    cua_so_lookback: int   = 7,
    rr1:             float = 1.0,
    rr2:             float = 2.0,
    vni_trend_map:   dict  = None,
) -> Optional[Dict]:
    """
    Phân tích đầy đủ 1 mã theo chỉ báo DÒNG TIỀN & XU HƯỚNG PRO.
    Trả về None nếu không đủ dữ liệu.
    """
    from screener import format_vnd

    MIN_BARS = max(ema_slow + 10, 60)
    if df is None or len(df) < MIN_BARS:
        return None

    # Ghép nến live (thời gian thực trong giờ giao dịch)
    if live_price > 0 and live_vol > 0:
        import time as _time
        c = live_price
        h = live_high if live_high > 0 else max(c, float(df['high'].iloc[-1]))
        l = live_low  if live_low  > 0 else min(c, float(df['low'].iloc[-1]))
        today = pd.DataFrame([{
            'time': int(_time.time()), 'open': float(df['open'].iloc[-1]),
            'high': h, 'low': l, 'close': c, 'volume': live_vol
        }])
        df = pd.concat([df, today], ignore_index=True)

    close = df['close']
    n = len(df)

    # 1. Nadaraya-Watson (Gaussian kernel non-repaint)
    actual_win = min(nw_win, n)
    nw_out_s   = calc_nadaraya_watson(close, nw_h, actual_win)
    actual_mae = min(499, n // 2)
    _, nw_upper_s, nw_lower_s = calc_nw_bands(close, nw_out_s, nw_mult, actual_mae)

    # 2. SuperTrend (Keltner ST)
    direction, st_line = calc_supertrend(df, st_len, st_mult, atr_len)

    # 3. ATR
    atr_s   = calc_atr(df, atr_len)
    cur_atr = float(atr_s.iloc[-1])

    # 4. Xác nhận đa khung D & W
    state_d, state_w = calc_mtf_states(df, ema_fast, ema_slow)

    # 5. Khóa trạng thái tín hiệu và vị thế
    state = track_positions_and_signals(
        df, direction, nw_upper_s, nw_lower_s, atr_s,
        cua_so_lookback=cua_so_lookback, rr1=rr1, rr2=rr2,
        vni_trend_map=vni_trend_map
    )

    # Giá hiện tại
    cur_price = live_price if live_price > 0 else float(close.iloc[-1])

    # Kế hoạch giá theo lệnh (nếu có vị thế active thì dùng entry/sl/tp của vị thế đó, ngược lại tính theo giá hiện tại)
    dir_val = state['direction']
    if state['entry_p'] > 0:
        entry_price = state['entry_p']
        sl_val      = state['sl_p']
        tp1_val     = state['tp1_p']
        tp2_val     = state['tp2_p']
    else:
        entry_price = cur_price
        risk = cur_atr * 1.5
        if dir_val == 1:
            sl_val, tp1_val, tp2_val = cur_price - risk, cur_price + risk * rr1, cur_price + risk * rr2
        else:
            sl_val, tp1_val, tp2_val = cur_price + risk, cur_price - risk * rr1, cur_price - risk * rr2

    sl_pct  = (sl_val  - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
    tp1_pct = (tp1_val - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
    tp2_pct = (tp2_val - entry_price) / entry_price * 100 if entry_price > 0 else 0.0

    # Labels
    trend_lbl = "TĂNG (BULLISH) 🟢" if dir_val == 1 else "GIẢM (BEARISH) 🔴"
    def mtf_str(v):
        return "TĂNG 🟢" if v == 1 else ("GIẢM 🔴" if v == -1 else "NGANG ⚪")

    # Volume ratio
    vol_ma = float(df['volume'].rolling(20).mean().iloc[-1])
    vr     = float(df['volume'].iloc[-1]) / vol_ma if vol_ma > 0 else 0.0

    return {
        'symbol':             symbol.upper(),
        'exchange':           exchange.upper(),
        'price':              cur_price,
        'price_vnd':          format_vnd(cur_price),
        'change_pct':         change_pct,
        'atr':                cur_atr,
        # NW
        'nw_out':             float(nw_out_s.iloc[-1]),
        'nw_upper':           state['nw_upper'],
        'nw_lower':           state['nw_lower'],
        'nw_zone_label':      state['nw_zone_label'],
        'in_day_nw':          state['in_day_nw'],
        'in_dinh_nw':         state['in_dinh_nw'],
        'had_nw_low':         state['had_nw_low'],
        'had_nw_high':        state['had_nw_high'],
        'bars_since_nw_low':  state['bars_since_nw_low'],
        'bars_since_nw_high': state['bars_since_nw_high'],
        # Trend & MTF
        'direction':          dir_val,
        'trend_label':        trend_lbl,
        'state_d':            state_d,
        'state_w':            state_w,
        'state_d_str':        mtf_str(state_d),
        'state_w_str':        mtf_str(state_w),
        # Tín hiệu phiên hôm nay
        'has_signal':         state['has_signal'],
        'is_buy':             state['is_buy'],
        'is_sell':            state['is_sell'],
        'buy_diamond':        state['buy_diamond'],
        'buy_standard':       state['buy_standard'],
        'sell_diamond':       state['sell_diamond'],
        'sell_standard':      state['sell_standard'],
        'signal_str':         state['signal_str'],
        # Vị thế & Lệnh
        'active_pos':         state['active_pos'],
        'pos_name':           state['pos_name'],
        'str_pos':            state['str_pos'],
        'pnl_pct':            state['pnl_pct'],
        'bars_since_trigger': state['bars_since_trigger'],
        # Volume
        'vol_ratio':          round(vr, 2),
        # Quản trị rủi ro
        'entry_price':        entry_price,
        'entry_price_vnd':    format_vnd(entry_price),
        'sl':                 sl_val,
        'sl_vnd':             format_vnd(sl_val),
        'sl_pct':             sl_pct,
        'tp1':                tp1_val,
        'tp1_vnd':            format_vnd(tp1_val),
        'tp1_pct':            tp1_pct,
        'tp2':                tp2_val,
        'tp2_vnd':            format_vnd(tp2_val),
        'tp2_pct':            tp2_pct,
        # Meta
        'updated_time':       datetime.now().strftime("%H:%M %d/%m/%Y"),
        'nw_bars_used':       actual_win,
        'buy_stats':          state.get('buy_stats', {}),
        'last_vni_up':        state.get('last_vni_up', True),
    }

