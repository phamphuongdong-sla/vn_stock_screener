# -*- coding: utf-8 -*-
"""
gdnl_indicators.py — Chỉ báo kỹ thuật PORT 100% từ Pine Script:
"GDNL - Vùng Xu Hướng PRO (Clean UI)"

Bao gồm:
  - ATR(14)
  - EMA nhanh/chậm (20/50)
  - ADX + DI+/DI- (14)
  - SuperTrend (EMA hlc3 10, hệ số ATR 2.8)
  - Volume MA(20)
  - Pivot High/Low (15 bars)
  - BOS / CHoCH cấu trúc
  - Liquidity Sweep
  - MTF State (proxy bằng EMA lookback khác nhau trên D)
  - Trend Score (0-6)
  - Tín hiệu MUA / BÁN
  - SL, TP1, TP2
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple, List, Dict


# ─────────────────────────────────────────────
# 1. CÁC HÀM CƠ BẢN
# ─────────────────────────────────────────────

def calc_atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """True Range và ATR (RMA = Wilder's smoothing = EMA alpha=1/length)."""
    high = df['high']
    low  = df['low']
    prev_close = df['close'].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs()
    ], axis=1).max(axis=1)
    # RMA (Wilder) = EMA với alpha = 1/length
    atr = tr.ewm(alpha=1.0 / length, adjust=False).mean()
    return atr


def calc_ema(series: pd.Series, length: int) -> pd.Series:
    """EMA chuẩn Pine Script: alpha = 2/(length+1)."""
    return series.ewm(span=length, adjust=False).mean()


def calc_rma(series: pd.Series, length: int) -> pd.Series:
    """RMA (Wilder's Moving Average) = EMA alpha = 1/length."""
    return series.ewm(alpha=1.0 / length, adjust=False).mean()


def calc_adx_dmi(df: pd.DataFrame, length: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Tính ADX + DI+ + DI- theo đúng chuẩn Pine Script ta.dmi(length, length).
    Returns: (di_plus, di_minus, adx)
    """
    high  = df['high']
    low   = df['low']
    close = df['close']

    up   = high.diff()
    down = -low.diff()

    plus_dm  = np.where((up > down) & (up > 0), up,  0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    plus_dm_s  = pd.Series(plus_dm,  index=df.index)
    minus_dm_s = pd.Series(minus_dm, index=df.index)

    # ATR dùng RMA
    high2 = df['high']
    low2  = df['low']
    prev_close = close.shift(1)
    tr = pd.concat([
        high2 - low2,
        (high2 - prev_close).abs(),
        (low2  - prev_close).abs()
    ], axis=1).max(axis=1)
    atr_rma = calc_rma(tr, length)

    di_plus  = 100.0 * calc_rma(plus_dm_s,  length) / atr_rma.replace(0, np.nan)
    di_minus = 100.0 * calc_rma(minus_dm_s, length) / atr_rma.replace(0, np.nan)
    di_plus  = di_plus.ffill().fillna(0)
    di_minus = di_minus.ffill().fillna(0)

    dx_sum = di_plus + di_minus
    dx = 100.0 * (di_plus - di_minus).abs() / dx_sum.replace(0, 1.0)
    adx = calc_rma(dx, length)

    return di_plus, di_minus, adx


def calc_supertrend(df: pd.DataFrame, st_length: int = 10, atr_mult: float = 2.8,
                    atr_length: int = 14) -> Tuple[pd.Series, pd.Series]:
    """
    SuperTrend port 100% Pine Script:
      stBasis  = ta.ema(hlc3, supertrendLength)
      upper/lower với ratchet mechanism
      direction 1=bull, -1=bear
    Returns: (direction_series, st_line_series)
    """
    hlc3 = (df['high'] + df['low'] + df['close']) / 3.0
    atr  = calc_atr(df, atr_length)
    st_basis = calc_ema(hlc3, st_length)

    upper_basic = st_basis + atr_mult * atr
    lower_basic = st_basis - atr_mult * atr

    close = df['close'].values
    ub = upper_basic.values
    lb = lower_basic.values
    n  = len(close)

    upper_final = np.full(n, np.nan)
    lower_final = np.full(n, np.nan)
    direction   = np.ones(n, dtype=int)

    # Pine Script var float ratchet
    for i in range(n):
        if i == 0:
            upper_final[i] = ub[i]
            lower_final[i] = lb[i]
            direction[i]   = 1
        else:
            # upperFinal
            if np.isnan(upper_final[i-1]):
                upper_final[i] = ub[i]
            else:
                if ub[i] < upper_final[i-1] or close[i-1] > upper_final[i-1]:
                    upper_final[i] = ub[i]
                else:
                    upper_final[i] = upper_final[i-1]

            # lowerFinal
            if np.isnan(lower_final[i-1]):
                lower_final[i] = lb[i]
            else:
                if lb[i] > lower_final[i-1] or close[i-1] < lower_final[i-1]:
                    lower_final[i] = lb[i]
                else:
                    lower_final[i] = lower_final[i-1]

            # direction
            prev_dir = direction[i-1]
            if prev_dir == -1 and close[i] > upper_final[i-1]:
                direction[i] = 1
            elif prev_dir == 1 and close[i] < lower_final[i-1]:
                direction[i] = -1
            else:
                direction[i] = prev_dir

    direction_s = pd.Series(direction, index=df.index)
    # st line = lowerFinal when bull, upperFinal when bear
    st_line = pd.Series(
        np.where(direction == 1, lower_final, upper_final),
        index=df.index
    )
    return direction_s, st_line


# ─────────────────────────────────────────────
# 2. PIVOT HIGH / LOW
# ─────────────────────────────────────────────

def detect_pivots(df: pd.DataFrame, length: int = 15) -> Tuple[pd.Series, pd.Series]:
    """
    Phát hiện Pivot High / Pivot Low theo ta.pivothigh/pivotlow(high, length, length).
    Returns: (ph_series, pl_series) — NaN nếu không phải pivot, giá trị nếu là pivot.
    Pivot được xác nhận tại index i khi high[i] là cao nhất trong [i-length, i+length].
    """
    high = df['high'].values
    low  = df['low'].values
    n    = len(df)

    ph = np.full(n, np.nan)
    pl = np.full(n, np.nan)

    for i in range(length, n - length):
        window_h = high[i - length: i + length + 1]
        if high[i] == np.max(window_h) and np.sum(window_h == high[i]) == 1:
            ph[i] = high[i]

        window_l = low[i - length: i + length + 1]
        if low[i] == np.min(window_l) and np.sum(window_l == low[i]) == 1:
            pl[i] = low[i]

    return pd.Series(ph, index=df.index), pd.Series(pl, index=df.index)


# ─────────────────────────────────────────────
# 3. BOS / CHoCH & SWEEP
# ─────────────────────────────────────────────

def detect_structure_and_sweep(
    df: pd.DataFrame,
    ph_series: pd.Series,
    pl_series: pd.Series
) -> Dict[str, pd.Series]:
    """
    Port Pine Script BOS/CHoCH logic và Liquidity Sweep.

    BOS  = Break of Structure (cùng chiều xu hướng hiện tại)
    CHoCH= Change of Character (đảo chiều xu hướng)
    Sweep= Quét thanh khoản (xuất hiện bóng nến vượt swing rồi đóng cửa ngược lại)

    Returns dict with keys:
      'bull_break', 'bear_break', 'bull_sweep', 'bear_sweep',
      'structure_label'  (BOS / CHoCH / nan)
    """
    close = df['close'].values
    high  = df['high'].values
    low   = df['low'].values
    n     = len(df)

    bull_break  = np.zeros(n, dtype=bool)
    bear_break  = np.zeros(n, dtype=bool)
    bull_sweep  = np.zeros(n, dtype=bool)
    bear_sweep  = np.zeros(n, dtype=bool)
    struct_lbl  = np.full(n, '', dtype=object)

    last_swing_high = np.nan
    last_swing_low  = np.nan
    high_broken     = False
    low_broken      = False
    structure_trend = 0  # 0=none, 1=bull, -1=bear

    ph_vals = ph_series.values
    pl_vals = pl_series.values

    for i in range(1, n):
        # Cập nhật swing
        if not np.isnan(ph_vals[i]):
            last_swing_high = ph_vals[i]
            high_broken = False
        if not np.isnan(pl_vals[i]):
            last_swing_low = pl_vals[i]
            low_broken = False

        # BOS / CHoCH bull
        if (not high_broken
                and not np.isnan(last_swing_high)
                and close[i] > last_swing_high
                and close[i-1] <= last_swing_high):
            bull_break[i] = True
            lbl = "CHoCH" if structure_trend == -1 else "BOS"
            struct_lbl[i] = f"{lbl}↑"
            structure_trend = 1
            high_broken = True

        # BOS / CHoCH bear
        if (not low_broken
                and not np.isnan(last_swing_low)
                and close[i] < last_swing_low
                and close[i-1] >= last_swing_low):
            bear_break[i] = True
            lbl = "CHoCH" if structure_trend == 1 else "BOS"
            struct_lbl[i] = f"{lbl}↓"
            structure_trend = -1
            low_broken = True

        # Sweep bull (rút chân dưới swing low rồi đóng cửa trên)
        if (not np.isnan(last_swing_low)
                and low[i] < last_swing_low
                and close[i] > last_swing_low):
            bull_sweep[i] = True

        # Sweep bear (xuyên qua swing high rồi đóng cửa dưới)
        if (not np.isnan(last_swing_high)
                and high[i] > last_swing_high
                and close[i] < last_swing_high):
            bear_sweep[i] = True

    return {
        'bull_break':    pd.Series(bull_break,  index=df.index),
        'bear_break':    pd.Series(bear_break,  index=df.index),
        'bull_sweep':    pd.Series(bull_sweep,  index=df.index),
        'bear_sweep':    pd.Series(bear_sweep,  index=df.index),
        'structure_label': pd.Series(struct_lbl, index=df.index),
    }


# ─────────────────────────────────────────────
# 4. MTF STATE (Proxy bằng lookback khác nhau)
# ─────────────────────────────────────────────

def calc_mtf_state(df: pd.DataFrame,
                   ema_fast: int = 20,
                   ema_slow: int = 50,
                   adx_len: int = 14,
                   adx_min: float = 18.0,
                   lookback: int = 0) -> int:
    """
    Tính trạng thái xu hướng MTF theo logic Pine Script f_mtfState().
    Trên khung D, mô phỏng H1/M30/M5 bằng cách lấy slice `lookback` nến cuối.
    lookback=0  → dùng toàn bộ df (H1 proxy)
    lookback>0  → dùng slice df[-lookback:] (M30/M5 proxy)

    Returns: 1 (bull), -1 (bear), 0 (neutral)
    """
    if lookback > 0:
        df = df.tail(max(lookback, ema_slow + adx_len + 5)).reset_index(drop=True)

    if len(df) < ema_slow + adx_len:
        return 0

    close = df['close']
    f_ema = calc_ema(close, ema_fast)
    s_ema = calc_ema(close, ema_slow)
    di_plus, di_minus, adx = calc_adx_dmi(df, adx_len)

    c = close.iloc[-1]
    fe = f_ema.iloc[-1]
    se = s_ema.iloc[-1]
    dp = di_plus.iloc[-1]
    dm = di_minus.iloc[-1]
    ax = adx.iloc[-1]

    if c > fe and fe > se and dp > dm and ax >= adx_min:
        return 1
    elif c < fe and fe < se and dm > dp and ax >= adx_min:
        return -1
    return 0


# ─────────────────────────────────────────────
# 5. TREND SCORE & SIGNALS
# ─────────────────────────────────────────────

def calc_trend_score_and_signals(
    df: pd.DataFrame,
    direction: pd.Series,
    di_plus: pd.Series,
    di_minus: pd.Series,
    adx: pd.Series,
    ema_fast: pd.Series,
    ema_slow: pd.Series,
    bull_break: pd.Series,
    bear_break: pd.Series,
    mtf_h1: int,
    mtf_m30: int,
    mtf_m5: int,
    adx_min: float = 18.0,
    vol_ma: pd.Series = None,
    min_score: int = 4,
) -> Dict:
    """
    Tính bullScore / bearScore / trendScore và buySignal / sellSignal.

    Pine:
      bullScore = direction==1 + emaFast>emaSlow + adx>=min + diPlus>diMinus + volumeOK + bullMTF
      bearScore = direction==-1 + emaFast<emaSlow + adx>=min + diMinus>diPlus + volumeOK + bearMTF
      buySignal = bullScore>=minScore AND (turnBull OR bullPullback OR bullBreak)
    """
    close = df['close']
    low   = df['low']
    high  = df['high']
    vol   = df['volume']

    dir_val   = direction.iloc[-1]
    dir_prev  = direction.iloc[-2] if len(direction) > 1 else dir_val
    dp        = di_plus.iloc[-1]
    dm        = di_minus.iloc[-1]
    ax        = adx.iloc[-1]
    ef        = ema_fast.iloc[-1]
    es        = ema_slow.iloc[-1]
    ef_prev   = ema_fast.iloc[-2] if len(ema_fast) > 1 else ef
    c         = close.iloc[-1]
    c_prev    = close.iloc[-2] if len(close) > 1 else c
    l         = low.iloc[-1]
    h         = high.iloc[-1]

    vol_ok = True
    if vol_ma is not None and len(vol_ma) > 0:
        vm = vol_ma.iloc[-1]
        if not np.isnan(vm) and vm > 0:
            vol_ok = float(vol.iloc[-1]) >= vm

    bull_mtf_ok = (1 if mtf_h1 == 1 else 0) + (1 if mtf_m30 == 1 else 0) + (1 if mtf_m5 == 1 else 0) >= 1
    bear_mtf_ok = (1 if mtf_h1 == -1 else 0) + (1 if mtf_m30 == -1 else 0) + (1 if mtf_m5 == -1 else 0) >= 1

    bull_score = (
        (1 if dir_val == 1 else 0) +
        (1 if ef > es else 0) +
        (1 if ax >= adx_min else 0) +
        (1 if dp > dm else 0) +
        (1 if vol_ok else 0) +
        (1 if bull_mtf_ok else 0)
    )
    bear_score = (
        (1 if dir_val == -1 else 0) +
        (1 if ef < es else 0) +
        (1 if ax >= adx_min else 0) +
        (1 if dm > dp else 0) +
        (1 if vol_ok else 0) +
        (1 if bear_mtf_ok else 0)
    )
    trend_score = bull_score if dir_val == 1 else bear_score

    # Trigger conditions
    turn_bull = (dir_val == 1 and dir_prev == -1)
    turn_bear = (dir_val == -1 and dir_prev == 1)

    # Crossover close vs emaFast
    bull_pullback = (dir_val == 1 and c > ef and c_prev <= ef_prev and l <= ef)
    bear_pullback = (dir_val == -1 and c < ef and c_prev >= ef_prev and h >= ef)

    bb = bool(bull_break.iloc[-1])
    be = bool(bear_break.iloc[-1])

    buy_signal  = (bull_score >= min_score) and (turn_bull or bull_pullback or bb)
    sell_signal = (bear_score >= min_score) and (turn_bear or bear_pullback or be)

    if buy_signal:
        signal_str = "MUA ĐẢO CHIỀU 🔄" if turn_bull else ("MUA BOS ↗️" if bb else "MUA TIẾP DIỄN 📈")
    elif sell_signal:
        signal_str = "BÁN ĐẢO CHIỀU 🔄" if turn_bear else ("BÁN BOS ↘️" if be else "BÁN TIẾP DIỄN 📉")
    else:
        signal_str = "CHỜ TÍN HIỆU ⏸"

    return {
        'bull_score':   bull_score,
        'bear_score':   bear_score,
        'trend_score':  trend_score,
        'buy_signal':   buy_signal,
        'sell_signal':  sell_signal,
        'signal_str':   signal_str,
        'turn_bull':    turn_bull,
        'turn_bear':    turn_bear,
        'adx':          round(float(ax), 1),
        'di_plus':      round(float(dp), 1),
        'di_minus':     round(float(dm), 1),
        'ema_fast':     float(ef),
        'ema_slow':     float(es),
        'direction':    int(dir_val),
        'mtf_h1':       mtf_h1,
        'mtf_m30':      mtf_m30,
        'mtf_m5':       mtf_m5,
    }


# ─────────────────────────────────────────────
# 6. RISK LEVELS (SL, TP1, TP2)
# ─────────────────────────────────────────────

def calc_risk_levels_gdnl(
    close: float,
    direction: int,
    atr: float,
    tp1_rr: float = 1.0,
    tp2_rr: float = 2.0,
    atr_sl_mult: float = 1.5
) -> Dict:
    """
    SL = close ± atr * 1.5 (theo Pine Script dashboard)
    TP1 = close ± risk * tp1RR
    TP2 = close ± risk * tp2RR
    """
    risk = atr * atr_sl_mult
    if direction == 1:
        sl  = close - risk
        tp1 = close + risk * tp1_rr
        tp2 = close + risk * tp2_rr
    else:
        sl  = close + risk
        tp1 = close - risk * tp1_rr
        tp2 = close - risk * tp2_rr

    sl_pct  = (sl  - close) / close * 100
    tp1_pct = (tp1 - close) / close * 100
    tp2_pct = (tp2 - close) / close * 100

    return {
        'sl':      sl,
        'tp1':     tp1,
        'tp2':     tp2,
        'sl_pct':  sl_pct,
        'tp1_pct': tp1_pct,
        'tp2_pct': tp2_pct,
        'risk':    risk,
    }


# ─────────────────────────────────────────────
# 7. HÀM TỔNG HỢP: ANALYZE_GDNL
# ─────────────────────────────────────────────

def analyze_gdnl(
    df: pd.DataFrame,
    symbol: str = "",
    exchange: str = "",
    live_price: float = 0.0,
    live_vol: float = 0.0,
    change_pct: float = 0.0,
    # Tham số Pine Script
    st_length: int = 10,
    atr_length: int = 14,
    atr_mult: float = 2.8,
    ema_fast_len: int = 20,
    ema_slow_len: int = 50,
    adx_len: int = 14,
    adx_min: float = 18.0,
    vol_len: int = 20,
    pivot_len: int = 15,
    tp1_rr: float = 1.0,
    tp2_rr: float = 2.0,
    min_score: int = 4,
) -> Optional[Dict]:
    """
    Hàm phân tích chính: nhận DataFrame lịch sử nến ngày, trả về dict kết quả.
    Trả về None nếu không đủ dữ liệu.
    """
    from screener import normalize_price_k, format_vnd, get_elapsed_trading_minutes
    from datetime import datetime

    min_bars = max(ema_slow_len, pivot_len * 2 + 5, atr_length) + 10
    if df is None or len(df) < min_bars:
        return None

    # ── Ghép nến thực (nếu có live data)
    if live_price > 0 and live_vol > 0:
        import time as _time
        today = pd.DataFrame([{
            'time':   int(_time.time()),
            'open':   float(df['open'].iloc[-1]),
            'high':   max(live_price, float(df['high'].iloc[-1])),
            'low':    min(live_price, float(df['low'].iloc[-1])),
            'close':  live_price,
            'volume': live_vol
        }])
        df = pd.concat([df, today], ignore_index=True)

    close = df['close']
    vol   = df['volume']

    # ── Chỉ báo
    atr_series  = calc_atr(df, atr_length)
    ema_fast    = calc_ema(close, ema_fast_len)
    ema_slow    = calc_ema(close, ema_slow_len)
    vol_ma      = vol.rolling(vol_len).mean()
    di_plus, di_minus, adx = calc_adx_dmi(df, adx_len)
    direction, st_line = calc_supertrend(df, st_length, atr_mult, atr_length)

    # ── MTF (proxy: dùng các lookback khác nhau)
    mtf_h1  = calc_mtf_state(df, ema_fast_len, ema_slow_len, adx_len, adx_min, lookback=0)
    mtf_m30 = calc_mtf_state(df, ema_fast_len, ema_slow_len, adx_len, adx_min, lookback=max(60, ema_slow_len + 5))
    mtf_m5  = calc_mtf_state(df, ema_fast_len, ema_slow_len, adx_len, adx_min, lookback=max(80, ema_slow_len + 5))

    # ── Pivot, cấu trúc
    ph_s, pl_s = detect_pivots(df, pivot_len)
    struct     = detect_structure_and_sweep(df, ph_s, pl_s)

    # ── Score & Signal
    sig = calc_trend_score_and_signals(
        df, direction, di_plus, di_minus, adx,
        ema_fast, ema_slow,
        struct['bull_break'], struct['bear_break'],
        mtf_h1, mtf_m30, mtf_m5,
        adx_min, vol_ma, min_score,
    )

    # ── Giá hiện tại
    current_price = live_price if live_price > 0 else float(close.iloc[-1])
    current_atr   = float(atr_series.iloc[-1])
    dir_val       = sig['direction']

    # ── Risk levels
    risk = calc_risk_levels_gdnl(current_price, dir_val, current_atr, tp1_rr, tp2_rr)

    # ── Labels giao diện
    trend_label = "TĂNG MẠNH 🟢" if dir_val == 1 else "GIẢM MẠNH 🔴"
    ef = sig['ema_fast']
    es = sig['ema_slow']
    cloud_label = "Trên Mây ☁️🟢" if current_price >= ef else "Dưới Mây ☁️🔴"

    def mtf_str(v):
        return "TĂNG 🟢" if v == 1 else ("GIẢM 🔴" if v == -1 else "NGANG ⚪")

    # ── Cấu trúc mới nhất
    lbl_arr = struct['structure_label'].values
    last_struct = ""
    for x in reversed(lbl_arr):
        if x:
            last_struct = x
            break

    # ── Volume ratio
    vm_val = float(vol_ma.iloc[-1]) if not np.isnan(float(vol_ma.iloc[-1])) else 1.0
    vr = float(vol.iloc[-1]) / vm_val if vm_val > 0 else 0.0

    # ── Thời gian
    now_str = datetime.now().strftime("%H:%M %d/%m/%Y")

    return {
        # Định danh
        'symbol':       symbol.upper(),
        'exchange':     exchange.upper(),
        # Giá
        'price':        current_price,
        'price_vnd':    format_vnd(current_price),
        'change_pct':   change_pct,
        'atr':          current_atr,
        # Xu hướng
        'direction':    dir_val,
        'trend_label':  trend_label,
        'cloud_label':  cloud_label,
        'adx':          sig['adx'],
        'di_plus':      sig['di_plus'],
        'di_minus':     sig['di_minus'],
        # Volume
        'vol_ratio':    round(vr, 2),
        'vol_ma':       vm_val,
        # MTF
        'mtf_h1':       mtf_h1,
        'mtf_m30':      mtf_m30,
        'mtf_m5':       mtf_m5,
        'mtf_h1_str':   mtf_str(mtf_h1),
        'mtf_m30_str':  mtf_str(mtf_m30),
        'mtf_m5_str':   mtf_str(mtf_m5),
        # Score & Signal
        'trend_score':  sig['trend_score'],
        'bull_score':   sig['bull_score'],
        'bear_score':   sig['bear_score'],
        'buy_signal':   sig['buy_signal'],
        'sell_signal':  sig['sell_signal'],
        'signal_str':   sig['signal_str'],
        # Cấu trúc
        'last_struct':  last_struct,
        # Risk
        'sl':           risk['sl'],
        'tp1':          risk['tp1'],
        'tp2':          risk['tp2'],
        'sl_pct':       risk['sl_pct'],
        'tp1_pct':      risk['tp1_pct'],
        'tp2_pct':      risk['tp2_pct'],
        # Metadata
        'updated_time': now_str,
    }
