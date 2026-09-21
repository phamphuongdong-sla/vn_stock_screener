# -*- coding: utf-8 -*-
import screener
import main

tickers = ['SSI', 'HPG', 'VND', 'BSR', 'DIG', 'PVD', 'VHM', 'MWG', 'FPT', 'KBC', 'GEX', 'STB']
signals = []

for s in tickers:
    item = {'stockSymbol': s}
    res = screener.analyze_stock(item, 'HOSE')
    if res:
        signals.append(res)

signals = sorted(signals, key=lambda x: (x["is_whale"], x["vol_ratio"]), reverse=True)
print("\n" + "="*80)
print("🎯 KẾT QUẢ PHÂN TÍCH THỰC TẾ TRÊN CÁC CỔ PHIẾU NỔI BẬT TẠI VIỆT NAM:")
print("="*80)
main.display_and_notify_results(signals)
