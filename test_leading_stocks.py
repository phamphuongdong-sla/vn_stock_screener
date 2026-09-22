# -*- coding: utf-8 -*-
"""
Script quét toàn bộ thị trường chứng khoán Việt Nam (HOSE + HNX)
Tự động kích hoạt bởi GitHub Actions theo lịch trình (Cron)
"""
import screener
import main

def main_scan():
    print("\n" + "="*80)
    print("🚀 GITHUB ACTIONS: KHỞI CHẠY QUÉT TOÀN BỘ THỊ TRƯỜNG CHỨNG KHOÁN (HOSE, HNX)")
    print("🎯 Lọc điểm mua chuẩn theo chỉ báo Pine Script AI Cá Mập ProMax")
    print("="*80)
    signals = screener.run_screener()
    main.display_and_notify_results(signals)

if __name__ == "__main__":
    main_scan()
