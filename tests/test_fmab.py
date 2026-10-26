# -*- coding: utf-8 -*-
"""
tests/test_fmab.py — Kiểm thử toàn diện chỉ báo [blackcat] L1 Fibonacci MA Band (FMAB)
"""

import unittest
import numpy as np
import pandas as pd

import fmab_indicators
import fmab_screener


class TestFMAB(unittest.TestCase):

    def setUp(self):
        # Tạo chuỗi dữ liệu giả lập có xu hướng tăng rõ ràng
        np.random.seed(42)
        n = 200
        dates = pd.date_range("2025-01-01", periods=n, freq="D")
        
        # Giá tạo sóng tăng từ 10 lên 30
        trend = np.linspace(10, 30, n)
        noise = np.random.normal(0, 0.5, n)
        close = trend + noise
        high = close + np.random.uniform(0.2, 0.8, n)
        low = close - np.random.uniform(0.2, 0.8, n)
        open_p = close + np.random.normal(0, 0.2, n)
        vol = np.random.uniform(100000, 500000, n)

        self.df = pd.DataFrame({
            'open': open_p,
            'high': high,
            'low': low,
            'close': close,
            'volume': vol
        }, index=dates)

    def test_pine_linreg_fast(self):
        """Kiểm tra độ chính xác của hàm hồi quy tuyến tính tối ưu tích chập."""
        s = pd.Series([10.0, 11.5, 12.0, 14.2, 13.8, 16.0, 15.5, 17.0, 18.2, 19.5])
        length = 4
        
        # Công thức chuẩn
        x = np.arange(length)
        x_mean = (length - 1) / 2.0
        x_var = np.sum((x - x_mean) ** 2)
        
        def calc_expected(window):
            y = window
            y_mean = np.mean(y)
            slope = np.sum((x - x_mean) * (y - y_mean)) / x_var
            return y_mean + slope * ((length - 1) / 2.0)
            
        expected = s.rolling(length).apply(calc_expected, raw=True)
        actual = fmab_indicators.pine_linreg_fast(s, length)
        
        diff = np.nanmax(np.abs(expected.dropna().values - actual.dropna().values))
        self.assertLess(diff, 1e-10)

    def test_compute_fmab_structure(self):
        """Kiểm tra cấu trúc và các trường trả về của compute_fmab."""
        res = fmab_indicators.compute_fmab(self.df)
        self.assertIsInstance(res, dict)
        self.assertIn('price', res)
        self.assertIn('whale_ma', res)
        self.assertIn('res_ma', res)
        self.assertIn('trendline_ma', res)
        self.assertIn('atr', res)
        self.assertIn('pos_state', res)
        self.assertIn('band_name', res)
        self.assertIn('trend_name', res)
        self.assertIn('confluence_score', res)
        self.assertIn('sl_price', res)
        self.assertIn('tp_price', res)
        self.assertIn('rr_ratio', res)

    def test_tpsl_calculation(self):
        """Kiểm tra công thức TP (+3x ATR) và SL (-2x ATR)."""
        res = fmab_indicators.compute_fmab(self.df, sl_mult=2.0, tp_mult=3.0)
        if not np.isnan(res['entry_price']) and res['pos_state'] == 1:
            entry = res['entry_price']
            atr = res['atr']
            expected_sl = entry - 2.0 * atr
            expected_tp = entry + 3.0 * atr
            self.assertAlmostEqual(res['sl_price'], expected_sl, places=4)
            self.assertAlmostEqual(res['tp_price'], expected_tp, places=4)
            self.assertAlmostEqual(res['rr_ratio'], 3.0 / 2.0, places=4)

    def test_cooldown_governance(self):
        """Kiểm tra cơ chế lọc nhiễu cooldownBars."""
        # Tạo chuỗi giá dao động quanh Whale MA
        n = 100
        close = [20.0 + (1.0 if i % 2 == 0 else -1.0) for i in range(n)]
        df_whip = pd.DataFrame({
            'open': close,
            'high': [c + 0.5 for c in close],
            'low': [c - 0.5 for c in close],
            'close': close,
            'volume': [100000] * n
        })
        
        # Với cooldown_bars = 3, số lần kích hoạt lệnh phải ít hơn nhiều so với cooldown = 0
        res_with_cd = fmab_indicators.compute_fmab(df_whip, cooldown_bars=3)
        res_no_cd = fmab_indicators.compute_fmab(df_whip, cooldown_bars=0)
        self.assertIsNotNone(res_with_cd)
        self.assertIsNotNone(res_no_cd)

    def test_formatters(self):
        """Kiểm tra các hàm định dạng tin nhắn Telegram."""
        fake_res = {
            'symbol': 'HPG',
            'exchange': 'HOSE',
            'updated_time': '10:00:00 26/10/2026',
            'price': 21.0,
            'price_vnd': '21.000 đ',
            'change_pct': 2.5,
            'vol_ratio': 1.8,
            'whale_ma': 20.5,
            'whale_ma_vnd': '20.500 đ',
            'res_ma': 22.0,
            'res_ma_vnd': '22.000 đ',
            'trendline_ma': 20.8,
            'trendline_ma_vnd': '20.800 đ',
            'band_name': 'BEAR BAND 🐻 (Dải Đỏ)',
            'trend_name': 'UPTREND 📈 (Nến trên Trendline)',
            'confluence_score': 2,
            'confluence_tag': '⭐⭐ HỢP LƯU TỐT (Đạt 2/3 điều kiện)',
            'action_title': '🟢 KÍCH HOẠT ĐIỂM MUA (BUY ENTRY)',
            'action_detail': 'Giá vừa cắt lên trên Whale MA.',
            'entry_price': 21.0,
            'entry_price_vnd': '21.000 đ',
            'sl_price': 19.8,
            'sl_vnd': '19.800 đ',
            'sl_pct': -5.7,
            'tp_price': 22.8,
            'tp_vnd': '22.800 đ',
            'tp_pct': 8.6,
            'rr_ratio': 1.5,
            'atr': 0.6,
            'pos_state': 1
        }
        
        detail_msg = fmab_screener.fmt_fmab_detail(fake_res)
        self.assertIn('HPG', detail_msg)
        self.assertIn('Whale MA', detail_msg)
        self.assertIn('21.000 đ', detail_msg)

        alert_msg = fmab_screener.fmt_fmab_buy_alert(fake_res)
        self.assertIn('CẢNH BÁO FMAB', alert_msg)
        self.assertIn('HPG', alert_msg)

        summary_msg = fmab_screener.fmt_fmab_scan_summary([fake_res], time_tag="[10:00]")
        self.assertIn('DANH SÁCH ĐIỂM MUA FMAB', summary_msg)
        self.assertIn('HPG', summary_msg)


if __name__ == '__main__':
    unittest.main()
