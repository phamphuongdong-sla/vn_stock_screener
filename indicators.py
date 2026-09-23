# -*- coding: utf-8 -*-
"""
AI & Keltner SuperTrend - Pro UI Technical Analysis Indicator Engine
Converted faithfully from TradingView Pine Script ("AI & Keltner SuperTrend - Pro UI").

Mathematical Parity:
1. Keltner Channel:
   ma = ta.sma(src, keltnerLength)
   rangec = high - low
   upperKeltner = ma + rangec
   lowerKeltner = ma - rangec
   rangec = upperKeltner - lowerKeltner = 2 * (high - low)
2. SuperTrend:
   upperBand = close + factor * rangec
   lowerBand = close - factor * rangec
   Ratcheting:
     lowerBand := lowerBand > prevLowerBand or close[1] < prevLowerBand ? lowerBand : prevLowerBand
     upperBand := upperBand < prevUpperBand or close[1] > prevUpperBand ? upperBand : prevUpperBand
   Direction:
     direction = 1 if na(rangec[1]) else (-1 if close > upperBand else 1) if prevSuperTrend == prevUpperBand else (1 if close < lowerBand else -1)
     st_value = lowerBand if direction == -1 else upperBand
3. EMA Ribbon:
   ema9  = ta.ema(high, 9)
   ema21 = ta.ema(high, 21)
   ema33 = ta.ema(high, 33)
   ema45 = ta.ema(high, 45)
   ribbon_bull = close > ema45
4. Trend Cloud:
   cloud_ref = ta.sma(st_value, 15)
5. Signals & Risk Management:
   bull = ta.crossover(close, st_value)
   bear = ta.crossunder(close, st_value)
   atr_val = ta.atr(atrLength)
   if bull:
     sl = low - (atr_val * 1.5)
     tp = close + ((close - sl) * rr_ratio)
   if bear:
     sl = high + (atr_val * 1.5)
     tp = close - ((sl - close) * rr_ratio)
"""

from typing import Dict, Optional, Tuple, Union
import numpy as np
import pandas as pd


def calc_sma(series: pd.Series, length: int) -> pd.Series:
    """Simple Moving Average (SMA)."""
    if length <= 0:
        raise ValueError("length must be a positive integer > 0")
    return series.rolling(window=length, min_periods=length).mean()


def calc_ema(series: pd.Series, length: int) -> pd.Series:
    """Exponential Moving Average (EMA) with Wilder/Pine Script initialization.
    
    Formula:
        EMA[length - 1] = mean(series[0:length])
        alpha = 2 / (length + 1)
        EMA[i] = alpha * series[i] + (1 - alpha) * EMA[i - 1]
    """
    if length <= 0:
        raise ValueError("length must be a positive integer > 0")

    n = len(series)
    if n < length:
        return pd.Series(np.nan, index=series.index, dtype=np.float64, name=f"ema{length}")

    s = series.to_numpy(dtype=np.float64)
    ema = np.full(n, np.nan, dtype=np.float64)
    
    # Initialize with SMA of first `length` valid values
    ema[length - 1] = np.mean(s[:length])
    alpha = 2.0 / (length + 1.0)
    one_minus_alpha = 1.0 - alpha

    for i in range(length, n):
        ema[i] = alpha * s[i] + one_minus_alpha * ema[i - 1]

    return pd.Series(ema, index=series.index, dtype=np.float64, name=f"ema{length}")


def calc_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    length: int = 14,
) -> pd.Series:
    """Average True Range (ATR) using Wilder's RMA smoothing (Pine Script ta.atr).
    
    Formula:
        TR[0] = high[0] - low[0]
        TR[i] = max(high[i] - low[i], |high[i] - close[i - 1]|, |low[i] - close[i - 1]|)
        ATR[length - 1] = mean(TR[0:length])
        ATR[i] = (TR[i] + (length - 1) * ATR[i - 1]) / length  for i >= length
    """
    if length <= 0:
        raise ValueError("length must be a positive integer > 0")

    n = len(close)
    if n < length:
        return pd.Series(np.nan, index=close.index, dtype=np.float64, name="atr")

    h = high.to_numpy(dtype=np.float64)
    l = low.to_numpy(dtype=np.float64)
    c = close.to_numpy(dtype=np.float64)

    tr = np.zeros(n, dtype=np.float64)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))

    atr = np.full(n, np.nan, dtype=np.float64)
    atr[length - 1] = np.mean(tr[:length])
    alpha = 1.0 / float(length)
    one_minus_alpha = 1.0 - alpha

    for i in range(length, n):
        atr[i] = alpha * tr[i] + one_minus_alpha * atr[i - 1]

    return pd.Series(atr, index=close.index, dtype=np.float64, name="atr")


def calc_keltner_supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    sensitivity: float = 2.8,
    keltner_length: int = 10,
) -> Tuple[pd.Series, pd.Series]:
    """Keltner SuperTrend from Corys Buy and Sell / AI & Keltner SuperTrend.

    Pine Script Reference:
        keltner_channel(src, length) =>
            ma = ta.sma(src, length)
            rangec = high - low
            upper = ma + rangec
            lower = ma - rangec
            [upper, lower]

        supertrend(_src, factor, kelLength) =>
            [upperKeltner, lowerKeltner] = keltner_channel(_src, kelLength)
            rangec = upperKeltner - lowerKeltner
            upperBand = _src + factor * rangec
            lowerBand = _src - factor * rangec
            
            prevLowerBand = nz(lowerBand[1])
            prevUpperBand = nz(upperBand[1])
            
            lowerBand := lowerBand > prevLowerBand or close[1] < prevLowerBand ? lowerBand : prevLowerBand
            upperBand := upperBand < prevUpperBand or close[1] > prevUpperBand ? upperBand : prevUpperBand
            
            int direction = na
            float st = na
            prevSuperTrend = st[1]

            if na(rangec[1])
                direction := 1
            else if prevSuperTrend == prevUpperBand
                direction := close > upperBand ? -1 : 1
            else
                direction := close < lowerBand ? 1 : -1
                
            st := direction == -1 ? lowerBand : upperBand
            [st, direction]

    Returns:
        Tuple of (st_dir, st_value):
            st_dir: -1 for Bullish (Uptrend), 1 for Bearish (Downtrend)
            st_value: Support lowerBand (when bull) or resistance upperBand (when bear)
    """
    n = len(close)
    st_dir = np.full(n, np.nan, dtype=np.float64)
    st_value = np.full(n, np.nan, dtype=np.float64)

    if n < keltner_length:
        return (
            pd.Series(st_dir, index=close.index, dtype=np.float64, name="st_dir"),
            pd.Series(st_value, index=close.index, dtype=np.float64, name="st_value"),
        )

    h = high.to_numpy(dtype=np.float64)
    l = low.to_numpy(dtype=np.float64)
    c = close.to_numpy(dtype=np.float64)

    upper_band = np.zeros(n, dtype=np.float64)
    lower_band = np.zeros(n, dtype=np.float64)

    for i in range(n):
        if i < keltner_length - 1:
            st_dir[i] = 1.0
            st_value[i] = np.nan
            continue

        # Keltner channel rangec = upperKeltner - lowerKeltner = 2 * (high - low)
        rangec = 2.0 * (h[i] - l[i])
        raw_ub = c[i] + sensitivity * rangec
        raw_lb = c[i] - sensitivity * rangec

        if i == keltner_length - 1:
            # At this bar, rangec[1] is still na in Pine Script
            lower_band[i] = raw_lb
            upper_band[i] = raw_ub
            st_dir[i] = 1.0
            st_value[i] = raw_ub
        else:
            prev_lb = lower_band[i - 1]
            prev_ub = upper_band[i - 1]
            c_prev = c[i - 1]

            lb = raw_lb if (raw_lb > prev_lb or c_prev < prev_lb) else prev_lb
            ub = raw_ub if (raw_ub < prev_ub or c_prev > prev_ub) else prev_ub
            lower_band[i] = lb
            upper_band[i] = ub

            prev_st = st_value[i - 1]
            if abs(prev_st - prev_ub) < 1e-9:
                direction = -1.0 if c[i] > ub else 1.0
            else:
                direction = 1.0 if c[i] < lb else -1.0

            st_dir[i] = direction
            st_value[i] = lb if direction == -1.0 else ub

    return (
        pd.Series(st_dir, index=close.index, dtype=np.float64, name="st_dir"),
        pd.Series(st_value, index=close.index, dtype=np.float64, name="st_value"),
    )


def calc_ema_ribbon(high: pd.Series, close: pd.Series) -> Dict[str, pd.Series]:
    """Calculates EMA Ribbon (EMA 9, 21, 33, 45 of High) and ribbon status."""
    ema9 = calc_ema(high, 9)
    ema21 = calc_ema(high, 21)
    ema33 = calc_ema(high, 33)
    ema45 = calc_ema(high, 45)
    ribbon_bull = close > ema45

    return {
        "ema9": ema9,
        "ema21": ema21,
        "ema33": ema33,
        "ema45": ema45,
        "ribbon_bull": ribbon_bull,
    }


def calc_signals(
    close: pd.Series,
    st_value: pd.Series,
) -> Tuple[pd.Series, pd.Series]:
    """Calculates Crossover (Bull) and Crossunder (Bear) signals for SuperTrend.

    Pine Script Reference:
        bull = ta.crossover(close, st_value)
        bear = ta.crossunder(close, st_value)
    """
    n = len(close)
    bull = np.zeros(n, dtype=bool)
    bear = np.zeros(n, dtype=bool)

    c = close.to_numpy(dtype=np.float64)
    st = st_value.to_numpy(dtype=np.float64)

    for i in range(1, n):
        if np.isnan(st[i]) or np.isnan(st[i - 1]):
            continue
        bull[i] = (c[i] > st[i]) and (c[i - 1] <= st[i - 1])
        bear[i] = (c[i] < st[i]) and (c[i - 1] >= st[i - 1])

    return (
        pd.Series(bull, index=close.index, name="bull"),
        pd.Series(bear, index=close.index, name="bear"),
    )


def calculate_all_indicators(
    df: pd.DataFrame,
    sensitivity: float = 2.8,
    keltner_length: int = 10,
    atr_length: int = 14,
    rr_ratio: float = 1.5,
) -> pd.DataFrame:
    """Calculates all indicators for AI & Keltner SuperTrend - Pro UI.

    Added columns:
        st_dir: SuperTrend direction (-1 = Bullish, 1 = Bearish)
        st_value: SuperTrend support/resistance value
        st_bull: Boolean (st_dir == -1)
        st_bear: Boolean (st_dir == 1)
        cloud_ref: SMA(st_value, 15) for Trend Cloud
        ema9, ema21, ema33, ema45: EMA of High
        ribbon_bull: Boolean (close > ema45)
        atr14: ATR(14)
        bull: Boolean crossover(close, st_value) -> MUA
        bear: Boolean crossunder(close, st_value) -> BÁN
        sl: Stop Loss calculated at signal bar
        tp: Take Profit (1.5R) calculated at signal bar
    """
    col_map = {col.lower(): col for col in df.columns}
    for req in ("high", "low", "close"):
        if req not in col_map:
            raise ValueError(f"DataFrame must contain column '{req}' (case-insensitive).")

    res = df.copy()
    high = res[col_map["high"]]
    low = res[col_map["low"]]
    close = res[col_map["close"]]

    # 1. Keltner SuperTrend
    st_dir, st_value = calc_keltner_supertrend(
        high=high, low=low, close=close,
        sensitivity=sensitivity, keltner_length=keltner_length
    )
    res["st_dir"] = st_dir
    res["st_value"] = st_value
    res["st_bull"] = st_dir == -1.0
    res["st_bear"] = st_dir == 1.0

    # 2. Trend Cloud (SMA of st_value over 15 bars)
    res["cloud_ref"] = calc_sma(st_value, 15)

    # 3. EMA Ribbon (High EMA 9, 21, 33, 45)
    ribbon = calc_ema_ribbon(high, close)
    res["ema9"] = ribbon["ema9"]
    res["ema21"] = ribbon["ema21"]
    res["ema33"] = ribbon["ema33"]
    res["ema45"] = ribbon["ema45"]
    res["ribbon_bull"] = ribbon["ribbon_bull"]

    # 4. ATR(14) for SL/TP
    res["atr14"] = calc_atr(high, low, close, length=atr_length)

    # 5. Signals: bull (crossover) / bear (crossunder)
    bull, bear = calc_signals(close, st_value)
    res["bull"] = bull
    res["bear"] = bear

    # 6. SL & TP values
    sl = np.full(len(close), np.nan, dtype=np.float64)
    tp = np.full(len(close), np.nan, dtype=np.float64)

    atr_vals = res["atr14"].to_numpy(dtype=np.float64)
    c_vals = close.to_numpy(dtype=np.float64)
    l_vals = low.to_numpy(dtype=np.float64)
    h_vals = high.to_numpy(dtype=np.float64)
    bull_vals = bull.to_numpy(dtype=bool)
    bear_vals = bear.to_numpy(dtype=bool)

    for i in range(len(close)):
        if bull_vals[i]:
            sl[i] = l_vals[i] - (atr_vals[i] * 1.5)
            tp[i] = c_vals[i] + ((c_vals[i] - sl[i]) * rr_ratio)
        elif bear_vals[i]:
            sl[i] = h_vals[i] + (atr_vals[i] * 1.5)
            tp[i] = c_vals[i] - ((sl[i] - c_vals[i]) * rr_ratio)
        else:
            # If currently in Bullish trend, calculate running SL/TP based on latest bar
            if st_dir.iloc[i] == -1.0:
                sl[i] = l_vals[i] - (atr_vals[i] * 1.5)
                tp[i] = c_vals[i] + ((c_vals[i] - sl[i]) * rr_ratio)
            else:
                sl[i] = h_vals[i] + (atr_vals[i] * 1.5)
                tp[i] = c_vals[i] - ((sl[i] - c_vals[i]) * rr_ratio)

    res["sl"] = sl
    res["tp"] = tp

    return res


def calc_risk_levels(
    close: float,
    low: float,
    atr: float,
    rr_ratio: float = 1.5,
) -> Dict[str, float]:
    """Calculates Stop Loss and Take Profit levels for Buy signals.
    
    Formula:
        SL = low - (atr * 1.5)
        TP1 (+1.0R) = close + (close - SL) * 1.0
        TP2 (+1.5R) = close + (close - SL) * rr_ratio
        TP3 (+2.5R) = close + (close - SL) * 2.5
    """
    sl = low - (atr * 1.5)
    risk = max(close - sl, close * 0.02)
    tp1 = close + risk * 1.0
    tp2 = close + risk * rr_ratio
    tp3 = close + risk * 2.5
    return {
        "sl": sl,
        "risk": risk,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
    }
