# -*- coding: utf-8 -*-
import screener
import pandas as pd

items = screener.get_exchange_symbols_snapshot("hose")
print(f"Tổng số mã sàn HOSE: {len(items)}")

# Chọn 10 mã thanh khoản lớn nhất hôm nay
valid_items = []
for item in items:
    symbol = item.get("stockSymbol") or item.get("ssi_symbol")
    if symbol and len(symbol) == 3 and symbol.isalpha():
        matched_price = item.get("matchedPrice", 0) or item.get("lastPrice", 0)
        total_vol = item.get("totalVol", 0) or item.get("nmTotalTradedQty", 0)
        total_val = item.get("totalVal", 0) or (matched_price * 1000 * total_vol)
        item["_calc_val"] = total_val
        valid_items.append(item)

valid_items.sort(key=lambda x: x["_calc_val"], reverse=True)
top10 = valid_items[:10]

for item in top10:
    symbol = item.get("stockSymbol") or item.get("ssi_symbol")
    df = screener.get_ticker_history(symbol, count=55)
    if df is not None and len(df) >= 35:
        screener.calculate_indicators(df)
        total_vol = item.get("totalVol", 0)
        vol_ma20 = df['vol_ma20'].iloc[-1]
        vol_ratio = total_vol / vol_ma20 if vol_ma20 > 0 else 0
        matched_price = item.get("matchedPrice", 0)
        
        today_open = item.get("open", 0) or df['open'].iloc[-1]
        today_high = item.get("high", 0) or df['high'].iloc[-1]
        today_low = item.get("low", 0) or df['low'].iloc[-1]
        change_pct = item.get("changePercent", 0) or 0
        candle_range = today_high - today_low
        lower_wick = min(today_open, matched_price) - today_low
        lower_wick_ratio = lower_wick / candle_range if candle_range > 0 else 0
        st = df['supertrend'].iloc[-1]
        cloud_max = df['cloud_max'].iloc[-1]

        print(f"Mã: {symbol} | Giá: {matched_price} ({change_pct:+.2f}%) | Vol: {total_vol:,} | MA20: {int(vol_ma20):,} | Vol gấp: {vol_ratio:.2f}x | Râu dưới: {lower_wick_ratio*100:.1f}% | SuperTrend: {st} | Trên mây: {matched_price >= cloud_max}")
    else:
        print(f"Mã: {symbol} -> Không tải được lịch sử nến (df={len(df) if df is not None else 'None'})")
