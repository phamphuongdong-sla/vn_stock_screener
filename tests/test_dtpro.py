# -*- coding: utf-8 -*-
"""
test_dtpro.py — Kiểm tra toàn diện hệ thống HỒ SƠ MUA/BÁN & HỖ TRỢ KHÁNG CỰ ĐỘNG:
1. Volume Profile (POC, Buy/Sell attribution)
2. Profile-Guided Dynamic S/R Engine (Pivots, Pull, Scoring 0-100, Breakout/Breakdown)
3. Đi lệnh 4 cấp độ: MUA DÒ, MUA CHÍNH, BÁN DÒ, BÁN HẾT
4. Quản trị rủi ro & Kế hoạch vào lệnh (Entry, SL max 7%, TP1, TP2)
5. Format tin nhắn Telegram (fmt_buy_alert, fmt_detail, fmt_scan_summary, fmt_stats_block)
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
        # Tạo dữ liệu giả lập chuẩn 150 nến
        np.random.seed(42)
        n = 150
        dates = pd.date_range("2025-01-01", periods=n, freq="D")
        ts = [int(d.timestamp()) for d in dates]

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

    def test_01_volume_profile(self):
        highs = self.df['high'].values
        lows = self.df['low'].values
        closes = self.df['close'].values
        vols = self.df['volume'].values

        bot, step, tot, buy = dtpro_indicators.compute_volume_profile(highs, lows, closes, vols, 0, len(self.df) - 1, rows=60)
        self.assertEqual(len(tot), 60)
        self.assertEqual(len(buy), 60)
        self.assertGreater(tot.sum(), 0)
        self.assertGreaterEqual(buy.sum(), 0)
        self.assertLessEqual(buy.sum(), tot.sum() + 1e-4)

    def test_02_supertrend_and_atr(self):
        st_dir, st_line = dtpro_indicators.calc_supertrend(self.df, st_len=10, atr_mult=2.8, atr_len=14)
        self.assertEqual(len(st_dir), len(self.df))
        self.assertTrue(set(st_dir.unique()).issubset({1, -1}))

        highs = self.df['high'].values
        lows = self.df['low'].values
        closes = self.df['close'].values
        atr = dtpro_indicators.calc_atr(highs, lows, closes, length=14)
        self.assertEqual(len(atr), len(self.df))
        self.assertTrue((atr > 0).all())

    def test_03_signals_and_risk(self):
        res = dtpro_indicators.analyze_dtpro(
            self.df, symbol="TEST", exchange="HOSE"
        )
        self.assertIsNotNone(res)
        self.assertIn('sig_mua_chinh', res)
        self.assertIn('sig_mua_do', res)
        self.assertIn('sig_ban_do', res)
        self.assertIn('sig_ban_het', res)
        self.assertIn('poc_price', res)
        self.assertIn('entry_price', res)
        self.assertIn('sl', res)
        self.assertIn('tp1', res)
        self.assertIn('buy_stats', res)

        cur_p = res['entry_price']
        sl = res['sl']
        tp1 = res['tp1']
        self.assertLess(sl, cur_p)
        self.assertGreater(tp1, cur_p)

    def test_04_market_relation(self):
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

    def test_05_formatting(self):
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
