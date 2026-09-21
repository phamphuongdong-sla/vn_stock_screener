# -*- coding: utf-8 -*-
"""
Script test nhanh các mã cổ phiếu thực tế tại Việt Nam
"""
import screener
import main

def test_quick():
    print("[*] Đang kết nối dữ liệu bảng giá thực tế sàn HOSE...")
    items = screener.get_exchange_symbols_snapshot("hose")
    print(f"[*] Nhận được {len(items)} mã. Lọc danh sách thanh khoản cao nhất để phân tích...")

    # Sắp xếp theo giá trị giao dịch cao nhất để phân tích top 40 mã dẫn dắt
    valid_items = []
    for item in items:
        symbol = item.get("stockSymbol") or item.get("ssi_symbol") or item.get("symbol")
        if symbol and len(symbol) == 3 and symbol.isalpha():
            matched_price = item.get("matchedPrice", 0) or item.get("lastPrice", 0)
            total_vol = item.get("totalVol", 0) or item.get("nmTotalTradedQty", 0)
            total_val = item.get("totalVal", 0) or (matched_price * 1000 * total_vol)
            item["_calc_val"] = total_val
            valid_items.append(item)

    valid_items.sort(key=lambda x: x["_calc_val"], reverse=True)
    top_items = valid_items[:40] # Quét top 40 mã dòng tiền mạnh nhất

    print(f"[*] Đang chạy thuật toán kiểm tra Dấu Chân Cá Mập trên top 40 mã...")
    signals = []
    for item in top_items:
        try:
            res = screener.analyze_stock(item, "HOSE")
            if res:
                signals.append(res)
        except Exception as e:
            continue

    signals = sorted(signals, key=lambda x: (x["is_whale"], x["vol_ratio"]), reverse=True)
    print(f"\n✅ KẾT QUẢ QUÉT THỰC TẾ TRÊN THỊ TRƯỜNG:")
    main.display_and_notify_results(signals)

if __name__ == "__main__":
    test_quick()
