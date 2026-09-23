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

    Pine Script equivalent:
        gaussKernel(x, h) = exp(-(x² / (h² * 2)))
        coefs[i] = gaussKernel(i, h)  for i in 0..499
        nwOut = sum(close[i] * coefs[i]) / sum(coefs)

    For each index t, result[t] = weighted average of close[t-0..t-(window-1)]
    (causal filter: uses only past & present data → non-repainting)
    """
    vals = close.values.astype(np.float64)
    n    = len(vals)
    weights = _gauss_weights(window, h)

    result = np.full(n, np.nan)
    for t in range(n):
        actual_w = min(window, t + 1)
        w = weights[:actual_w]
        # close[0]=vals[t], close[1]=vals[t-1], ...
        segment = vals[t - actual_w + 1 : t + 1][::-1]
        result[t] = np.dot(segment, w) / w.sum()

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
    Daily state  = MTF state of the daily df itself
    Weekly state = MTF state on weekly-resampled close
    Returns: (state_D, state_W)
    """
    # Daily: use full df
    state_d = _ema_state(df['close'], ema_fast, ema_slow)

    # Weekly: resample daily → weekly close (last close of each week)
    try:
        df_ts = df.copy()
        df_ts['date'] = pd.to_datetime(df_ts['time'], unit='s')
        df_ts = df_ts.set_index('date')
        weekly_close = df_ts['close'].resample('W').last().dropna()
        if len(weekly_close) >= ema_slow:
            state_w = _ema_state(weekly_close, ema_fast, ema_slow)
        else:
            state_w = state_d   # fallback
    except Exception:
        state_w = 0

    return state_d, state_w


# ─────────────────────────────────────────────
# 4. SIGNAL GENERATION
# ─────────────────────────────────────────────

def generate_signals(
    df: pd.DataFrame,
    direction: pd.Series,
    nw_upper: pd.Series,
    nw_lower: pd.Series,
) -> Dict:
    """
    Pine:
      buyTrigger  = dir==1 and dir[-1]==-1   (confirmed bar)
      sellTrigger = dir==-1 and dir[-1]==1

      isVungDayNW  = low  <= nwLower or crossunder(close, nwLower)
      isVungDinhNW = high >= nwUpper or crossover(close, nwUpper)

      buyDiamond  = buyTrigger  and isVungDayNW
      buyStandard = buyTrigger  and not isVungDayNW
      sellDiamond  = sellTrigger and isVungDinhNW
      sellStandard = sellTrigger and not isVungDinhNW
    """
    close  = df['close']
    high   = df['high']
    low    = df['low']

    dir_cur  = int(direction.iloc[-1])
    dir_prev = int(direction.iloc[-2]) if len(direction) > 1 else dir_cur

    buy_trigger  = (dir_cur == 1  and dir_prev == -1)
    sell_trigger = (dir_cur == -1 and dir_prev == 1)

    # NW zone detection at current bar
    nw_u = float(nw_upper.iloc[-1]) if not pd.isna(nw_upper.iloc[-1]) else np.inf
    nw_l = float(nw_lower.iloc[-1]) if not pd.isna(nw_lower.iloc[-1]) else -np.inf

    c_cur  = float(close.iloc[-1])
    c_prev = float(close.iloc[-2]) if len(close) > 1 else c_cur
    h_cur  = float(high.iloc[-1])
    l_cur  = float(low.iloc[-1])

    nw_u_prev = float(nw_upper.iloc[-2]) if len(nw_upper) > 1 and not pd.isna(nw_upper.iloc[-2]) else nw_u
    nw_l_prev = float(nw_lower.iloc[-2]) if len(nw_lower) > 1 and not pd.isna(nw_lower.iloc[-2]) else nw_l

    cross_down = (c_prev >= nw_l_prev) and (c_cur < nw_l)   # crossunder
    cross_up   = (c_prev <= nw_u_prev) and (c_cur > nw_u)   # crossover

    is_day_nw  = (l_cur <= nw_l) or cross_down   # vùng đáy NW
    is_dinh_nw = (h_cur >= nw_u) or cross_up      # vùng đỉnh NW

    buy_diamond   = buy_trigger  and is_day_nw
    buy_standard  = buy_trigger  and not is_day_nw
    sell_diamond  = sell_trigger and is_dinh_nw
    sell_standard = sell_trigger and not is_dinh_nw

    # Current NW zone (không cần trigger)
    in_day_nw  = l_cur <= nw_l or c_cur <= nw_l
    in_dinh_nw = h_cur >= nw_u or c_cur >= nw_u

    nw_zone_label = "VÙNG ĐÁY 💎" if in_day_nw else ("VÙNG ĐỈNH 🔥" if in_dinh_nw else "TRUNG BÌNH ⚪️")

    if buy_diamond:
        signal_str = "💎 MUA ĐÁY NW (Hội tụ tối ưu!)"
        has_signal = True
    elif buy_standard:
        signal_str = "🟢 MUA CHÍNH"
        has_signal = True
    elif sell_diamond:
        signal_str = "🔥 BÁN ĐỈNH NW (Hội tụ tối ưu!)"
        has_signal = True
    elif sell_standard:
        signal_str = "🔴 BÁN CHÍNH"
        has_signal = True
    else:
        signal_str = "⏸ CHỜ TÍN HIỆU"
        has_signal = False

    return {
        'buy_trigger':   buy_trigger,
        'sell_trigger':  sell_trigger,
        'buy_diamond':   buy_diamond,
        'buy_standard':  buy_standard,
        'sell_diamond':  sell_diamond,
        'sell_standard': sell_standard,
        'has_signal':    has_signal,
        'is_buy':        buy_trigger,
        'is_sell':       sell_trigger,
        'signal_str':    signal_str,
        'nw_zone_label': nw_zone_label,
        'in_day_nw':     in_day_nw,
        'in_dinh_nw':    in_dinh_nw,
        'nw_upper':      nw_u,
        'nw_lower':      nw_l,
        'direction':     dir_cur,
    }


# ─────────────────────────────────────────────
# 5. RISK MANAGEMENT
# ─────────────────────────────────────────────

def calc_risk(
    close: float,
    direction: int,
    atr: float,
    rr1: float = 1.0,
    rr2: float = 2.0,
    atr_sl_mult: float = 1.5,
) -> Dict:
    """SL = close ± atr*1.5, TP1 = close ± risk*rr1, TP2 = close ± risk*rr2"""
    risk = atr * atr_sl_mult
    if direction == 1:
        sl, tp1, tp2 = close - risk, close + risk * rr1, close + risk * rr2
    else:
        sl, tp1, tp2 = close + risk, close - risk * rr1, close - risk * rr2

    return {
        'sl':      sl,   'sl_pct':  (sl  - close) / close * 100,
        'tp1':     tp1,  'tp1_pct': (tp1 - close) / close * 100,
        'tp2':     tp2,  'tp2_pct': (tp2 - close) / close * 100,
        'risk':    risk,
    }


# ─────────────────────────────────────────────
# 6. HÀM TỔNG HỢP: ANALYZE_DTPRO
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
    # Params
    st_len:   int   = 10,
    atr_len:  int   = 14,
    st_mult:  float = 2.8,
    ema_fast: int   = 20,
    ema_slow: int   = 50,
    nw_h:     float = 8.0,
    nw_mult:  float = 3.0,
    nw_win:   int   = 500,
    rr1:      float = 1.0,
    rr2:      float = 2.0,
) -> Optional[Dict]:
    """
    Phân tích đầy đủ 1 mã theo chỉ báo DÒNG TIỀN PRO.
    Trả về None nếu không đủ dữ liệu.
    """
    from screener import format_vnd

    MIN_BARS = max(ema_slow + 10, 60)
    if df is None or len(df) < MIN_BARS:
        return None

    # ── Ghép nến live (nếu có)
    if live_price > 0 and live_vol > 0:
        import time as _time
        c = live_price
        h = live_high  if live_high > 0  else max(c, float(df['high'].iloc[-1]))
        l = live_low   if live_low  > 0  else min(c, float(df['low'].iloc[-1]))
        today = pd.DataFrame([{
            'time': int(_time.time()), 'open': float(df['open'].iloc[-1]),
            'high': h, 'low': l, 'close': c, 'volume': live_vol
        }])
        df = pd.concat([df, today], ignore_index=True)

    close = df['close']
    n = len(df)

    # ── Nadaraya-Watson (dùng toàn bộ lịch sử có sẵn)
    actual_win = min(nw_win, n)
    nw_out_s   = calc_nadaraya_watson(close, nw_h, actual_win)
    actual_mae = min(499, n // 2)
    _, nw_upper_s, nw_lower_s = calc_nw_bands(close, nw_out_s, nw_mult, actual_mae)

    # ── SuperTrend
    direction, st_line = calc_supertrend(df, st_len, st_mult, atr_len)

    # ── ATR
    atr_s   = calc_atr(df, atr_len)
    cur_atr = float(atr_s.iloc[-1])

    # ── MTF
    state_d, state_w = calc_mtf_states(df, ema_fast, ema_slow)

    # ── Signals
    sig = generate_signals(df, direction, nw_upper_s, nw_lower_s)

    # ── Giá hiện tại
    cur_price = live_price if live_price > 0 else float(close.iloc[-1])

    # ── Risk
    risk = calc_risk(cur_price, sig['direction'], cur_atr, rr1, rr2)

    # ── Labels
    dir_val   = sig['direction']
    trend_lbl = "TĂNG (BULLISH) 🟢" if dir_val == 1 else "GIẢM (BEARISH) 🔴"

    def mtf_str(v):
        return "TĂNG 🟢" if v == 1 else ("GIẢM 🔴" if v == -1 else "NGANG ⚪")

    # ── EMA info
    ef = float(calc_ema(close, ema_fast).iloc[-1])
    es = float(calc_ema(close, ema_slow).iloc[-1])

    # ── Volume ratio
    vol_ma = float(df['volume'].rolling(20).mean().iloc[-1])
    vr     = float(df['volume'].iloc[-1]) / vol_ma if vol_ma > 0 else 0.0

    return {
        'symbol':       symbol.upper(),
        'exchange':     exchange.upper(),
        'price':        cur_price,
        'price_vnd':    format_vnd(cur_price),
        'change_pct':   change_pct,
        'atr':          cur_atr,
        # NW
        'nw_out':       float(nw_out_s.iloc[-1]),
        'nw_upper':     sig['nw_upper'],
        'nw_lower':     sig['nw_lower'],
        'nw_zone_label': sig['nw_zone_label'],
        'in_day_nw':    sig['in_day_nw'],
        'in_dinh_nw':   sig['in_dinh_nw'],
        # Trend
        'direction':    dir_val,
        'trend_label':  trend_lbl,
        'ema_fast':     ef,
        'ema_slow':     es,
        # MTF
        'state_d':      state_d,
        'state_w':      state_w,
        'state_d_str':  mtf_str(state_d),
        'state_w_str':  mtf_str(state_w),
        # Signals
        'has_signal':    sig['has_signal'],
        'is_buy':        sig['is_buy'],
        'is_sell':       sig['is_sell'],
        'buy_diamond':   sig['buy_diamond'],
        'sell_diamond':  sig['sell_diamond'],
        'signal_str':    sig['signal_str'],
        # Volume
        'vol_ratio':     round(vr, 2),
        # Risk
        'sl':      risk['sl'],   'sl_pct':  risk['sl_pct'],
        'tp1':     risk['tp1'],  'tp1_pct': risk['tp1_pct'],
        'tp2':     risk['tp2'],  'tp2_pct': risk['tp2_pct'],
        # Meta
        'updated_time': datetime.now().strftime("%H:%M %d/%m/%Y"),
        'nw_bars_used': actual_win,
    }
