# -*- coding: utf-8 -*-
"""
Script quét toàn bộ thị trường chứng khoán Việt Nam (HOSE + HNX)
Chạy độc lập, không cần tương tác bàn phím, tối ưu cho GitHub Actions và Cron Scheduler.
"""
import screener
import main

def main_scan():
    print("[*] Khởi chạy quét toàn bộ thị trường chứng khoán...")
    signals = screener.run_screener()
    main.display_and_notify_results(signals)

if __name__ == "__main__":
    main_scan()
