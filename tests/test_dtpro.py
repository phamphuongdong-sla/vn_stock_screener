# -*- coding: utf-8 -*-
"""
test_dtpro.py — Kiểm tra toàn diện hệ thống DÒNG TIỀN & XU HƯỚNG PRO:
1. Indicator: SuperTrend, Nadaraya-Watson, EMA20/50, D, W
2. Signals: MUA, MUA MẠNH, BÁN, BÁN MẠNH
3. Market Context: VN TĂNG/GIẢM/NGANG, Đồng pha, Ngược pha, Trung tính
4. Risk: Entry, SL, TP1, TP2, R:R
5. Database: Insert, Read, Duplicate Prevention
6. Formatting: fmt_buy_alert, fmt_detail, fmt_stats_block
"""

import unittest
import numpy as np
import pandas as pd
import time
import os

import dtpro_indicators
import dtpro_screener
import dtpro_runner
import database


class TestDTPro(unittest.TestCase):

    def setUp(self):
        # Tạo dữ liệu giả lập chuẩn 100 nến
        np.random.seed(42)
        n = 150
        dates = pd.date_range("2025-01-01", periods=n, freq="D")
        ts = [int(d.timestamp()) for d in dates]

        # Chuỗi giá có sóng giảm rồi đảo chiều tăng
        base_p = 50.0 + np.sin(np.linspace(0, 10, n)) * 10
        noise = np.random.normal(0, 0.5, n)
        c = base_p + noise
        h = c + np.random.uniform(0.5, 1.5, n)
        l = c - np.random.uniform(0.5, 1.5, n)
        o = (h + l) / 2.0
        v = np.random.uniform(500000, 2000000, n)

        self.df = pd.DataFrame({
            'time': ts,
            'open': o,
            'high': h,
            'low': l,
            'close': c,
            'volume': v
        })

    def test_01_nadaraya_watson(self):
        nw_out = dtpro_indicators.calc_nadaraya_watson(self.df['close'], h=8.0, window=100)
        self.assertEqual(len(nw_out), len(self.df))
        self.assertFalse(nw_out.isna().any())

        nw_out, upper, lower = dtpro_indicators.calc_nw_bands(self.df['close'], nw_out, nw_mult=3.0, mae_window=50)
        self.assertTrue((upper >= nw_out).all())
        self.assertTrue((lower <= nw_out).all())

    def test_02_supertrend(self):
        st_dir, st_line = dtpro_indicators.calc_supertrend(self.df, st_len=10, atr_mult=2.8, atr_len=14)
        self.assertEqual(len(st_dir), len(self.df))
        self.assertTrue(set(st_dir.unique()).issubset({1, -1}))

    def test_03_mtf_states(self):
        state_d, state_w = dtpro_indicators.calc_mtf_states(self.df, ema_fast=20, ema_slow=50)
        self.assertIn(state_d, [1, -1, 0])
        self.assertIn(state_w, [1, -1, 0])

    def test_04_signals_and_risk(self):
        res = dtpro_indicators.analyze_dtpro(
            self.df, symbol="TEST", exchange="HOSE",
            st_len=10, atr_len=14, st_mult=2.8,
            ema_fast=20, ema_slow=50, nw_h=8.0, nw_mult=3.0
        )
        self.assertIsNotNone(res)
        self.assertIn('direction', res)
        self.assertIn('active_pos', res)
        self.assertIn('entry_price', res)
        self.assertIn('sl', res)
        self.assertIn('tp1', res)
        self.assertIn('tp2', res)

        # Kiểm tra công thức R:R
        cur_p = res['entry_price']
        sl = res['sl']
        tp1 = res['tp1']
        tp2 = res['tp2']
        if res['direction'] == 1:
            self.assertLess(sl, cur_p)
            self.assertGreater(tp1, cur_p)
            self.assertGreater(tp2, tp1)

    def test_05_market_relation(self):
        # Test 5 kịch bản quan hệ thị trường
        rel, badge, _, _ = dtpro_runner.calc_market_relation("TĂNG", "TĂNG", "VIC")
        self.assertEqual(rel, "ĐỒNG PHA")

        rel, badge, _, _ = dtpro_runner.calc_market_relation("TĂNG", "GIẢM", "VIC")
        self.assertEqual(rel, "NGƯỢC PHA")

        rel, badge, _, _ = dtpro_runner.calc_market_relation("GIẢM", "TĂNG", "VIC")
        self.assertEqual(rel, "NGƯỢC PHA")

        rel, badge, _, _ = dtpro_runner.calc_market_relation("GIẢM", "GIẢM", "VIC")
        self.assertEqual(rel, "ĐỒNG PHA")

        rel, badge, _, _ = dtpro_runner.calc_market_relation("NGANG", "NGANG", "VIC")
        self.assertEqual(rel, "TRUNG TÍNH")

    def test_06_database_duplicate_prevention(self):
        test_ts = int(time.time())
        sig = {
            'symbol': 'TEST_DUP',
            'timestamp': test_ts,
            'timeframe': '1D',
            'signal': 'BUY',
            'strength': 'DIAMOND',
            'entry': 100.0,
            'sl': 95.0,
            'tp1': 105.0,
            'tp2': 110.0,
            'atr': 3.3,
            'stock_trend': 'TĂNG',
            'trend_d': 'TĂNG',
            'trend_w': 'TĂNG',
            'vnindex_trend': 'TĂNG',
            'market_relation': 'ĐỒNG PHA',
            'status': 'ACTIVE',
        }
        res1 = database.save_signal(sig)
        self.assertTrue(res1)

        # Lần 2 phải bị từ chối
        res2 = database.save_signal(sig)
        self.assertFalse(res2)
        self.assertTrue(database.is_signal_exists('TEST_DUP', '1D', test_ts, 'BUY'))

    def test_07_formatting(self):
        res = dtpro_indicators.analyze_dtpro(
            self.df, symbol="VIC", exchange="HOSE"
        )
        res['vni'] = {'price': 1775.0, 'state': 'NGANG', 'state_str': '⚪ NGANG'}
        detail_msg = dtpro_runner.fmt_detail(res)
        alert_msg = dtpro_runner.fmt_buy_alert(res)

        self.assertIn("VIC", detail_msg)
        self.assertIn("THỊ TRƯỜNG CHUNG", detail_msg)
        self.assertIn("THỐNG KÊ 10 NĂM", detail_msg)
        self.assertIn("Tổng lệnh MUA", detail_msg)

        self.assertIn("VIC", alert_msg)
        self.assertIn("KẾ HOẠCH GIẢI NGÂN", alert_msg)
        self.assertIn("buy_stats", res)
        bs = res['buy_stats']
        self.assertIn('dia_vni_wins', bs)
        self.assertIn('std_vni_wins', bs)
        self.assertIn('tot_vni_wins', bs)
        self.assertIn('sell_tot_wins', bs)


if __name__ == "__main__":
    unittest.main()
