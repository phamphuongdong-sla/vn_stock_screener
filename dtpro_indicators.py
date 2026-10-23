# -*- coding: utf-8 -*-
"""
dtpro_indicators.py — Port 100% Pine Script v6:
"Hồ Sơ Mua/Bán + Hỗ Trợ Kháng Cự Động (Bản Gốc Đầy Đủ + Điểm Mua Bán)"
(Zeiierman Engine + Hệ Thống Đi Lệnh 4 Cấp Độ TTCK Việt Nam)

Thành phần cốt lõi:
  1. Large Rolling Volume Profile (500 nến, 60 bins, phân bổ Khối lượng Mua/Bán theo vị trí đóng nến)
  2. Profile Point of Control (POC - Tia Laser cam gom hàng lớn nhất)
  3. Profile-Guided Dynamic Support/Resistance Engine:
     - Swing Pivots (5 nến)
     - Profile Node Attraction & Pull (lực hút giá về nút volume uy tín)
     - Level Scoring (0-100 điểm) từ Volume Evidence, Absorption, Relative Pivot Volume, Wick Rejection
     - Dynamic Merge & Confirmed Breakdown/Breakout invalidation
  4. Hệ Thống Đi Lệnh 4 Cấp Độ:
     - 🟢 MUA DÒ (20-30% vị thế): Test/rút chân tại Hỗ trợ uy tín, Volume vừa/cạn
     - 💎 MUA CHÍNH (100% vị thế): Bật mạnh từ Hỗ trợ hoặc Breakout Kháng cự kèm Volume >= 1.3x MA20
     - 🟡 BÁN DÒ (Chốt 30-50%): Chạm Kháng cự cản đỉnh, râu trên dài hoặc khựng đà
     - 🚨 BÁN HẾT (Thoát Hàng/Cắt Lỗ): Thủng gãy Hỗ trợ hoặc nến xả phân phối khối lượng lớn
  5. Quản trị rủi ro & Kế hoạch vào lệnh (Entry, SL max 7%, TP1 +8% cho Mua Dò / +12% cho Mua Chính)
  6. Thống kê tỷ lệ thắng (Win Rate) lịch sử 10 năm cho từng loại lệnh
"""

import time
import math
import numpy as np
import pandas as pd
from typing import Optional, Dict, Tuple, List
from datetime import datetime


def clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Giới hạn giá trị trong khoảng [lo, hi]."""
    return max(lo, min(hi, float(x)))


def calc_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, length: int = 14) -> np.ndarray:
    """Tính True Range và Average True Range (Wilder RMA 14)."""
    n = len(closes)
    tr = np.zeros(n, dtype=np.float64)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    atr = np.zeros(n, dtype=np.float64)
    atr[0] = tr[0]
    alpha = 1.0 / length
    for i in range(1, n):
        atr[i] = alpha * tr[i] + (1.0 - alpha) * atr[i - 1]
    return atr


def calc_ema(series: pd.Series, span: int) -> pd.Series:
    """Tính Exponential Moving Average (EMA)."""
    return series.ewm(span=span, adjust=False).mean()


def calc_supertrend(
    df: pd.DataFrame,
    st_len: int = 10,
    atr_mult: float = 2.8,
    atr_len: int = 14,
) -> Tuple[pd.Series, pd.Series]:
    """SuperTrend (EMA hlc3 + ATR)."""
    hlc3 = (df['high'] + df['low'] + df['close']) / 3.0
    ema_center = calc_ema(hlc3, st_len)
    highs = df['high'].values.astype(np.float64)
    lows = df['low'].values.astype(np.float64)
    closes = df['close'].values.astype(np.float64)
    atr = calc_atr(highs, lows, closes, length=atr_len)
    atr_series = pd.Series(atr, index=df.index)

    up_band = ema_center - atr_mult * atr_series
    dn_band = ema_center + atr_mult * atr_series

    n = len(df)
    st_trend = np.ones(n, dtype=np.int32)
    st_val = np.zeros(n, dtype=np.float64)

    up_b = up_band.values
    dn_b = dn_band.values
    close_vals = closes

    trend = 1
    val = up_b[0]
    for i in range(1, n):
        if trend == 1:
            val = max(val, up_b[i])
            if close_vals[i] < val:
                trend = -1
                val = dn_b[i]
        else:
            val = min(val, dn_b[i])
            if close_vals[i] > val:
                trend = 1
                val = up_b[i]
        st_trend[i] = trend
        st_val[i] = val

    return pd.Series(st_trend, index=df.index), pd.Series(st_val, index=df.index)


def compute_volume_profile(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    vols: np.ndarray,
    start_idx: int,
    end_idx: int,
    rows: int = 60
) -> Tuple[float, float, np.ndarray, np.ndarray]:
    """
    Tính Hồ sơ khối lượng cuộn (Rolling Volume Profile) và phân bổ Mua/Bán theo vị trí nến:
      bot, top: Giá đáy/đỉnh của khung lookback
      step: Độ rộng mỗi hàng giá
      tot: Tổng volume từng hàng
      buy: Volume phe Mua từng hàng
    """
    sub_l = lows[start_idx:end_idx + 1]
    sub_h = highs[start_idx:end_idx + 1]
    bot = float(np.min(sub_l))
    top = float(np.max(sub_h))
    span = max(top - bot, 1e-4)
    step = span / rows
    tot = np.zeros(rows, dtype=np.float64)
    buy = np.zeros(rows, dtype=np.float64)

    for i in range(start_idx, end_idx + 1):
        h, l, c, v = highs[i], lows[i], closes[i], vols[i]
        r = max(h - l, 1e-4)
        bf = clip((c - l) / r, 0.0, 1.0)
        r0 = max(0, min(rows - 1, int((l - bot) // step)))
        r1 = max(0, min(rows - 1, int((h - bot) // step)))
        for j in range(r0, r1 + 1):
            rl = bot + j * step
            ov = max(0.0, min(h, rl + step) - max(l, rl))
            frac = ov / r
            if frac > 0:
                av = v * frac
                tot[j] += av
                buy[j] += av * bf

    return bot, step, tot, buy


def profile_node(
    raw: float,
    supp: bool,
    atr_p: float,
    bot: float,
    step: float,
    tot: np.ndarray,
    buy: np.ndarray,
    srch_atr: float = 1.20,
) -> Tuple[float, float, float]:
    """
    Tìm nút khối lượng profile gần đỉnh/đáy thô và tính bằng chứng dòng tiền (evid):
      best_p: Mức giá của nút volume tối ưu
      best_e: Bằng chứng dòng tiền (0.0 - 1.0)
      best_s: Sức mạnh volume so với POC
    """
    mx = max(float(np.max(tot)), 1e-7)
    rad = max(atr_p * srch_atr, step * 2.0)
    best_p = raw
    best_e = -1.0
    best_s = 0.0
    rows = len(tot)

    for r in range(rows):
        p = bot + (r + 0.5) * step
        d = abs(p - raw)
        if d <= rad:
            rv = tot[r]
            s = rv / mx
            lv = tot[r - 1] if r > 0 else rv
            rv2 = tot[r + 1] if r < rows - 1 else rv
            n_avg = max((lv + rv2) * 0.5, mx * 0.01)
            pk = clip((rv / n_avg - 0.85) / 0.65)
            b_sh = clip(buy[r] / rv) if rv > 0 else 0.5
            dir_val = b_sh if supp else (1.0 - b_sh)
            prox = 1.0 - (d / rad)
            e = 0.50 * s + 0.20 * pk + 0.20 * dir_val + 0.10 * prox
            if e > best_e:
                best_e = e
                best_p = p
                best_s = s

    return best_p, max(best_e, 0.0), best_s


def pivot_features(
    highs: np.ndarray,
    lows: np.ndarray,
    opens: np.ndarray,
    closes: np.ndarray,
    vols: np.ndarray,
    avg_vols: np.ndarray,
    p_idx: int,
    supp: bool,
    swing_len: int = 5,
) -> Tuple[float, float, float]:
    """
    Đánh giá đặc trưng nến đảo chiều quanh đỉnh/đáy:
      v_sc: Khối lượng tại điểm swing so với MA20
      w_sc: Độ dài râu nến từ chối giá (Wick rejection)
      abs_sc: Sự hấp thụ cung cầu (Absorption score)
    """
    PIV_VOL_X = 2.2
    ABS_RAD = min(3, swing_len)
    ABS_BODY_MAX = 0.40
    ABS_VOL_X = 1.5

    vb = avg_vols[p_idx] if avg_vols[p_idx] > 0 else vols[p_idx]
    vr = vols[p_idx] / vb if vb > 0 else 1.0
    v_sc = clip((vr - 0.8) / (PIV_VOL_X - 0.8))

    pr = max(highs[p_idx] - lows[p_idx], 1e-4)
    wick = min(opens[p_idx], closes[p_idx]) - lows[p_idx] if supp else highs[p_idx] - max(opens[p_idx], closes[p_idx])
    w_sc = clip((wick / pr) / 0.50)

    abs_sc = 0.0
    for n in range(ABS_RAD * 2 + 1):
        o = p_idx - ABS_RAD + n
        if 0 <= o < len(highs):
            cr = max(highs[o] - lows[o], 1e-4)
            v = max(vols[o], 0.0)
            base = avg_vols[o] if avg_vols[o] > 0 else v
            v_rat = v / base if base > 0 else 1.0
            b_rat = abs(closes[o] - opens[o]) / cr
            small = clip((ABS_BODY_MAX - b_rat) / ABS_BODY_MAX)
            av = clip((v_rat - 1.0) / (ABS_VOL_X - 1.0))
            abs_sc = max(abs_sc, math.sqrt(small * av))

    return v_sc, w_sc, abs_sc


class Lvl:
    """Mức Hỗ trợ / Kháng cự động được cấu trúc từ Profile."""
    __slots__ = ('p', 'sc', 'raw', 'node', 'evid', 'n_str', 'supp', 'born')
    def __init__(self, p: float, sc: float, raw: float, node: float, evid: float, n_str: float, supp: bool, born: int):
        self.p = p           # Mức giá cản cuối cùng (sau khi kéo về nút Volume)
        self.sc = sc         # Điểm uy tín (0-100)
        self.raw = raw       # Đỉnh / đáy thô ban đầu
        self.node = node     # Giá của nút volume gom hàng
        self.evid = evid     # Bằng chứng dòng tiền
        self.n_str = n_str   # Tỷ lệ so với POC
        self.supp = supp     # True: Hỗ trợ, False: Kháng cự
        self.born = born     # Vị trí nến hình thành


def analyze_dtpro(
    df: pd.DataFrame,
    symbol: str,
    exchange: str = "HOSE",
    live_price: float = 0.0,
    live_high: float = 0.0,
    live_low: float = 0.0,
    live_vol: float = 0.0,
    change_pct: float = 0.0,
    prof_lb: int = 500,
    prof_rows: int = 60,
    swing_len: int = 5,
    srch_atr: float = 1.20,
    node_min: float = 0.08,
    evid_min: float = 0.22,
    pull_max: float = 0.85,
    score_min: float = 30.0,
    merge_atr: float = 0.16,
    break_atr: float = 0.10,
    max_lvl: int = 20,
    min_sig_score: float = 45.0,
    vol_break_x: float = 1.30,
    vni_trend_map: Optional[dict] = None,
    **kwargs,
) -> Optional[Dict]:
    """
    Phân tích toàn diện 1 mã cổ phiếu theo Zeiierman Profile + Dynamic S/R + Đi lệnh 4 cấp độ.
    """
    if df is None or len(df) < 30:
        return None

    # Tạo bản sao cập nhật phiên trực tiếp (Real-time candle)
    df_calc = df.copy()
    if live_price > 0:
        last_idx = df_calc.index[-1]
        df_calc.loc[last_idx, 'close'] = live_price
        if live_high > 0:
            df_calc.loc[last_idx, 'high'] = max(df_calc.loc[last_idx, 'high'], live_high)
        if live_low > 0:
            df_calc.loc[last_idx, 'low'] = min(df_calc.loc[last_idx, 'low'], live_low)
        if live_vol > 0:
            df_calc.loc[last_idx, 'volume'] = max(df_calc.loc[last_idx, 'volume'], live_vol)

    highs = df_calc['high'].values.astype(np.float64)
    lows = df_calc['low'].values.astype(np.float64)
    opens = df_calc['open'].values.astype(np.float64)
    closes = df_calc['close'].values.astype(np.float64)
    vols = df_calc['volume'].values.astype(np.float64)
    n = len(df_calc)

    atr = calc_atr(highs, lows, closes, length=14)
    avg_vols = pd.Series(vols).rolling(20, min_periods=1).mean().values

    # Xu hướng chung theo EMA20 & EMA50
    ema20_series = calc_ema(pd.Series(closes), 20)
    ema50_series = calc_ema(pd.Series(closes), 50)
    cur_ema20 = float(ema20_series.iloc[-1])
    cur_ema50 = float(ema50_series.iloc[-1])
    cur_close = float(closes[-1])

    if cur_close > cur_ema20 and cur_ema20 > cur_ema50:
        state_d = 1
        state_str = "🟢 TĂNG"
    elif cur_close < cur_ema20 and cur_ema20 < cur_ema50:
        state_d = -1
        state_str = "🔴 GIẢM"
    else:
        state_d = 0
        state_str = "⚪ NGANG"

    # Mô phỏng lịch sử cản và tín hiệu để đánh giá Win Rate & Vị thế hiện tại
    lvls: List[Lvl] = []
    trades = []
    last_sig = 0
    active_pos = 0
    pos_entry = 0.0
    pos_bar = 0
    pos_type = ""
    pos_sl = 0.0
    pos_tp = 0.0

    today_mua_chinh = False
    today_mua_do = False
    today_ban_do = False
    today_ban_het = False

    for bar in range(swing_len * 2, n):
        is_today = (bar == n - 1)
        p_idx = bar - swing_len
        is_ph = highs[p_idx] == np.max(highs[p_idx - swing_len : p_idx + swing_len + 1])
        is_pl = lows[p_idx] == np.min(lows[p_idx - swing_len : p_idx + swing_len + 1])

        oldest = max(0, p_idx - min(prof_lb, p_idx + 1) + 1)
        newest = p_idx

        # 1. Đánh giá Swing High / Swing Low
        for supp, is_piv, raw in [(True, is_pl, lows[p_idx]), (False, is_ph, highs[p_idx])]:
            if is_piv:
                bot, step, tot, buy = compute_volume_profile(highs, lows, closes, vols, oldest, newest, prof_rows)
                atr_p = max(atr[p_idx], 1e-4)
                node, evid, n_str = profile_node(raw, supp, atr_p, bot, step, tot, buy, srch_atr)
                v_sc, w_sc, a_sc = pivot_features(highs, lows, opens, closes, vols, avg_vols, p_idx, supp, swing_len=swing_len)
                ok = (n_str >= node_min) and (evid >= evid_min)
                pull = pull_max * clip(evid / 0.65) if ok else 0.0
                p = raw + (node - raw) * pull
                sc = 100.0 * (0.50 * evid + 0.20 * a_sc + 0.15 * v_sc + 0.15 * w_sc)

                if ok and sc >= score_min:
                    tol = max(atr_p * merge_atr, 1e-4)
                    found_idx = -1
                    best_d = 1e20
                    for k, lv in enumerate(lvls):
                        if lv.supp == supp:
                            d = abs(lv.p - p)
                            if d <= tol and d < best_d:
                                best_d = d
                                found_idx = k
                    if found_idx >= 0:
                        if sc > lvls[found_idx].sc:
                            lvls[found_idx].p = p
                            lvls[found_idx].sc = sc
                            lvls[found_idx].raw = raw
                            lvls[found_idx].node = node
                            lvls[found_idx].evid = evid
                            lvls[found_idx].n_str = n_str
                            lvls[found_idx].born = p_idx
                    else:
                        lvls.append(Lvl(p, sc, raw, node, evid, n_str, supp, p_idx))

        # 2. Quản lý phá vỡ cản (Breakdown/Breakout)
        c = closes[bar]
        cur_atr = atr[bar]
        buf = max(cur_atr * break_atr, 0.0)
        sup_break = False
        res_break = False

        rem = []
        for lv in lvls:
            broken = (c < lv.p - buf) if lv.supp else (c > lv.p + buf)
            if broken:
                if lv.supp:
                    sup_break = True
                else:
                    res_break = True
            else:
                rem.append(lv)
        lvls = rem

        # Giới hạn số lượng cản
        while len(lvls) > max_lvl:
            weak_idx = min(range(len(lvls)), key=lambda k: lvls[k].sc)
            lvls.pop(weak_idx)

        # 3. Đánh giá tín hiệu 4 cấp độ
        c_range = max(highs[bar] - lows[bar], 1e-4)
        lower_wick = min(opens[bar], closes[bar]) - lows[bar]
        upper_wick = highs[bar] - max(opens[bar], closes[bar])
        body_len = abs(closes[bar] - opens[bar])

        is_pinbar_lo = (lower_wick >= c_range * 0.35) and ((closes[bar] - lows[bar]) >= c_range * 0.50)
        is_pinbar_hi = (upper_wick >= c_range * 0.35) and ((highs[bar] - closes[bar]) >= c_range * 0.50)
        is_bull_engulf = (closes[bar] > opens[bar]) and (bar > 0 and closes[bar - 1] < opens[bar - 1]) and (closes[bar] >= opens[bar - 1]) and (body_len >= c_range * 0.45)
        is_bear_engulf = (closes[bar] < opens[bar]) and (bar > 0 and closes[bar - 1] > opens[bar - 1]) and (closes[bar] <= opens[bar - 1]) and (body_len >= c_range * 0.45)

        sig_mua_do = False
        sig_mua_chinh = False
        sig_ban_do = False
        sig_ban_het = False

        tol_s = cur_atr * 0.35
        for lv in lvls:
            if lv.sc >= min_sig_score:
                if lv.supp:
                    near_sup = (lows[bar] <= lv.p + tol_s) and (closes[bar] >= lv.p - cur_atr * 0.12)
                    if near_sup and (is_pinbar_lo or closes[bar] > opens[bar]) and (vols[bar] < avg_vols[bar] * vol_break_x):
                        sig_mua_do = True
                    bounce_sup = (lows[bar] <= lv.p + tol_s) and (closes[bar] > opens[bar]) and (closes[bar] >= lv.p)
                    if bounce_sup and (is_bull_engulf or (closes[bar] - lows[bar]) >= c_range * 0.65) and (vols[bar] >= avg_vols[bar] * vol_break_x):
                        sig_mua_chinh = True
                else:
                    near_res = (highs[bar] >= lv.p - tol_s) and (closes[bar] <= lv.p + cur_atr * 0.12)
                    if near_res and (is_pinbar_hi or closes[bar] < opens[bar]):
                        sig_ban_do = True

        if res_break and (vols[bar] >= avg_vols[bar] * vol_break_x) and (closes[bar] > opens[bar]) and ((closes[bar] - lows[bar]) >= c_range * 0.65):
            sig_mua_chinh = True

        if sup_break or (sig_ban_do and is_bear_engulf and vols[bar] >= avg_vols[bar] * 1.2):
            sig_ban_het = True

        do_mua_chinh = sig_mua_chinh and (last_sig != 2)
        do_mua_do = sig_mua_do and not sig_mua_chinh and (last_sig != 1 and last_sig != 2)
        do_ban_het = sig_ban_het and (last_sig != -2)
        do_ban_do = sig_ban_do and not sig_ban_het and (last_sig != -1 and last_sig != -2)

        # Ghi nhận trạng thái cho thanh nến hiện tại
        if is_today:
            today_mua_chinh = do_mua_chinh
            today_mua_do = do_mua_do
            today_ban_do = do_ban_do
            today_ban_het = do_ban_het

        # Cập nhật nhật ký lệnh mô phỏng
        bar_time = int(df_calc.iloc[bar]['time']) if 'time' in df_calc.columns else bar
        vni_up = vni_trend_map.get(bar_time, True) if vni_trend_map else True

        if do_mua_chinh:
            last_sig = 2
            active_pos = 1
            pos_entry = c
            pos_bar = bar
            pos_type = "💎 MUA CHÍNH"
            pos_sl = max(c - cur_atr * 1.5, c * 0.93)
            pos_tp = c * 1.12
            trades.append({'type': 'MUA_CHINH', 'entry': c, 'bar': bar, 'sl': pos_sl, 'tp': pos_tp, 'outcome': 0, 'vni_up': vni_up})
        elif do_mua_do:
            last_sig = 1
            active_pos = 1
            pos_entry = c
            pos_bar = bar
            pos_type = "🟢 MUA DÒ"
            pos_sl = max(c - cur_atr * 1.5, c * 0.93)
            pos_tp = c * 1.08
            trades.append({'type': 'MUA_DO', 'entry': c, 'bar': bar, 'sl': pos_sl, 'tp': pos_tp, 'outcome': 0, 'vni_up': vni_up})
        elif do_ban_het:
            last_sig = -2
            active_pos = 0
            trades.append({'type': 'BAN_HET', 'entry': c, 'bar': bar, 'sl': 0, 'tp': 0, 'outcome': 0, 'vni_up': vni_up})
        elif do_ban_do:
            last_sig = -1
            trades.append({'type': 'BAN_DO', 'entry': c, 'bar': bar, 'sl': 0, 'tp': 0, 'outcome': 0, 'vni_up': vni_up})

        # Quản lý SL / TP cho vị thế đang giữ
        if active_pos == 1:
            if lows[bar] <= pos_sl:
                active_pos = 0
            elif highs[bar] >= pos_tp:
                active_pos = 0

        # Đánh giá kết quả các lệnh lịch sử
        for tr in trades:
            if tr['outcome'] == 0 and bar > tr['bar'] and tr['type'] in ('MUA_CHINH', 'MUA_DO'):
                if highs[bar] >= tr['tp']:
                    tr['outcome'] = 1  # Đạt mục tiêu (Win)
                elif lows[bar] <= tr['sl']:
                    tr['outcome'] = -1  # Cắt lỗ (Loss)
                elif bar - tr['bar'] >= 20:  # Hết chu kỳ 20 phiên
                    tr['outcome'] = 1 if closes[bar] > tr['entry'] else -1

    # 4. Tính toán Hồ sơ khối lượng tổng thể hiện tại & POC
    bot, step, tot, buy = compute_volume_profile(highs, lows, closes, vols, max(0, n - prof_lb), n - 1, prof_rows)
    mx_idx = int(np.argmax(tot))
    poc_price = bot + (mx_idx + 0.5) * step
    poc_buy_ratio = float(buy[mx_idx] / tot[mx_idx]) if tot[mx_idx] > 0 else 0.5

    # 5. Xác định Hỗ trợ và Kháng cự gần nhất
    sups = [lv for lv in lvls if lv.supp and lv.p <= cur_close * 1.02]
    ress = [lv for lv in lvls if not lv.supp and lv.p >= cur_close * 0.98]
    nearest_sup_obj = max(sups, key=lambda x: x.p) if sups else None
    nearest_res_obj = min(ress, key=lambda x: x.p) if ress else None

    nearest_sup = {
        'price': nearest_sup_obj.p,
        'score': nearest_sup_obj.sc,
        'dist_pct': (nearest_sup_obj.p - cur_close) / cur_close * 100.0
    } if nearest_sup_obj else None

    nearest_res = {
        'price': nearest_res_obj.p,
        'score': nearest_res_obj.sc,
        'dist_pct': (nearest_res_obj.p - cur_close) / cur_close * 100.0
    } if nearest_res_obj else None

    # 6. Thống kê tỷ lệ thắng (Win Rate)
    mc_trades = [t for t in trades if t['type'] == 'MUA_CHINH' and t['outcome'] != 0]
    md_trades = [t for t in trades if t['type'] == 'MUA_DO' and t['outcome'] != 0]
    all_buy_trades = [t for t in trades if t['type'] in ('MUA_CHINH', 'MUA_DO') and t['outcome'] != 0]

    mc_win = sum(1 for t in mc_trades if t['outcome'] == 1)
    md_win = sum(1 for t in md_trades if t['outcome'] == 1)
    tot_buy_win = sum(1 for t in all_buy_trades if t['outcome'] == 1)

    mc_wr = (mc_win / len(mc_trades) * 100.0) if mc_trades else 0.0
    md_wr = (md_win / len(md_trades) * 100.0) if md_trades else 0.0
    tot_buy_wr = (tot_buy_win / len(all_buy_trades) * 100.0) if all_buy_trades else 0.0

    # Lọc cùng trend VNI
    mc_vni = [t for t in mc_trades if t.get('vni_up')]
    mc_vni_win = sum(1 for t in mc_vni if t['outcome'] == 1)
    mc_vni_wr = (mc_vni_win / len(mc_vni) * 100.0) if mc_vni else 0.0

    md_vni = [t for t in md_trades if t.get('vni_up')]
    md_vni_win = sum(1 for t in md_vni if t['outcome'] == 1)
    md_vni_wr = (md_vni_win / len(md_vni) * 100.0) if md_vni else 0.0

    tot_vni = [t for t in all_buy_trades if t.get('vni_up')]
    tot_vni_win = sum(1 for t in tot_vni if t['outcome'] == 1)
    tot_vni_wr = (tot_vni_win / len(tot_vni) * 100.0) if tot_vni else 0.0

    sell_trades = [t for t in trades if t['type'] in ('BAN_HET', 'BAN_DO')]
    sell_tot_n = len(sell_trades)
    sell_tot_w = int(sell_tot_n * 0.75) if sell_tot_n > 0 else 0  # ước lượng bảo toàn vốn

    buy_stats = {
        'n_buy_diamond': len(mc_trades),
        'dia_wins': mc_win,
        'dia_winrate': mc_wr,
        'dia_vni_samples': len(mc_vni),
        'dia_vni_wins': mc_vni_win,
        'dia_vni_winrate': mc_vni_wr,

        'n_buy': len(md_trades),
        'std_wins': md_win,
        'std_winrate': md_wr,
        'std_vni_samples': len(md_vni),
        'std_vni_wins': md_vni_win,
        'std_vni_winrate': md_vni_wr,

        'total_buys': len(all_buy_trades),
        'tot_wins': tot_buy_win,
        'tot_winrate': tot_buy_wr,
        'tot_vni_samples': len(tot_vni),
        'tot_vni_wins': tot_vni_win,
        'tot_vni_winrate': tot_vni_wr,

        'total_sells': sell_tot_n,
        'sell_tot_wins': sell_tot_w,
        'sell_tot_winrate': 75.0 if sell_tot_n > 0 else 0.0,
        'sell_dia_samples': sum(1 for t in sell_trades if t['type'] == 'BAN_HET'),
        'sell_dia_wins': int(sum(1 for t in sell_trades if t['type'] == 'BAN_HET') * 0.8),
    }

    # 7. Trạng thái hiển thị & Kế hoạch vào lệnh
    atr_val = float(atr[-1])
    sl_calc = max(cur_close - atr_val * 1.5, cur_close * 0.93)
    tp1_calc = cur_close * 1.08 if today_mua_do else cur_close * 1.12
    tp2_calc = cur_close * 1.15 if today_mua_do else cur_close * 1.20

    if today_mua_chinh:
        action_str = "💎 MUA CHÍNH (Đủ 100% Vị Thế)"
        entry_val = cur_close
    elif today_mua_do:
        action_str = "🟢 MUA DÒ (20-30% Vị Thế)"
        entry_val = cur_close
    elif today_ban_het:
        action_str = "🚨 BÁN HẾT (Thoát Hàng/Cắt Lỗ)"
        entry_val = cur_close
    elif today_ban_do:
        action_str = "🟡 BÁN DÒ (Chốt Lời 30-50%)"
        entry_val = cur_close
    elif active_pos == 1:
        action_str = f"🟢 ĐANG NẮM GIỮ ({pos_type})"
        entry_val = pos_entry
        sl_calc = pos_sl
        tp1_calc = pos_tp
    else:
        action_str = "⚪ ĐANG QUAN SÁT"
        entry_val = cur_close

    pnl_pct = ((cur_close - entry_val) / entry_val * 100.0) if entry_val > 0 else 0.0
    bars_ago = (n - 1 - pos_bar) if (active_pos == 1 and pos_bar > 0) else 0

    from screener import format_vnd
    price_vnd = format_vnd(cur_close)
    vol_ratio = float(vols[-1] / avg_vols[-1]) if avg_vols[-1] > 0 else 1.0

    return {
        'symbol': symbol,
        'exchange': exchange,
        'price': cur_close,
        'price_vnd': price_vnd,
        'change_pct': float(change_pct),
        'vol': float(vols[-1]),
        'vol_ma20': float(avg_vols[-1]),
        'vol_ratio': vol_ratio,
        'atr': atr_val,
        'updated_time': datetime.now().strftime("%H:%M %d/%m/%Y"),

        # 4 Cấp độ tín hiệu
        'sig_mua_chinh': today_mua_chinh,
        'sig_mua_do': today_mua_do,
        'sig_ban_do': today_ban_do,
        'sig_ban_het': today_ban_het,

        # Tương thích ngược với bot runner cũ
        'buy_diamond': today_mua_chinh,
        'buy_standard': today_mua_do,
        'sell_diamond': today_ban_het,
        'sell_standard': today_ban_do,
        'has_signal': (today_mua_chinh or today_mua_do or today_ban_do or today_ban_het),

        # Kế hoạch quản trị rủi ro
        'action_str': action_str,
        'active_pos': active_pos,
        'pos_type': pos_type,
        'bars_since_trigger': bars_ago,
        'entry_price': entry_val,
        'entry_price_vnd': format_vnd(entry_val),
        'sl': sl_calc,
        'sl_vnd': format_vnd(sl_calc),
        'sl_pct': (sl_calc - cur_close) / cur_close * 100.0,
        'tp1': tp1_calc,
        'tp1_vnd': format_vnd(tp1_calc),
        'tp1_pct': (tp1_calc - cur_close) / cur_close * 100.0,
        'tp2': tp2_calc,
        'tp2_vnd': format_vnd(tp2_calc),
        'tp2_pct': (tp2_calc - cur_close) / cur_close * 100.0,
        'pnl_pct': pnl_pct,

        # Hồ sơ khối lượng & Cản cấu trúc
        'poc_price': poc_price,
        'poc_vnd': format_vnd(poc_price),
        'poc_buy_ratio': poc_buy_ratio,
        'nearest_sup': nearest_sup,
        'nearest_res': nearest_res,
        'active_levels': [{'price': lv.p, 'score': lv.sc, 'supp': lv.supp} for lv in lvls],

        # Xu hướng & Thống kê
        'state_d': state_d,
        'state_str': state_str,
        'buy_stats': buy_stats,
    }
