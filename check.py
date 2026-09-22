# -*- coding: utf-8 -*-
"""
Script soi chi tiết 1 mã cổ phiếu bất kỳ
Cách dùng:
  ./venv/bin/python3 check.py HPG
  ./venv/bin/python3 check.py SSI
  (hoặc chạy python3 check.py rồi nhập mã)
"""

import sys
import screener
import main
import telegram_bot
from tabulate import tabulate

def check_single_stock(symbol: str, send_telegram: bool = True, target_chat_id: str = None):
    symbol = symbol.strip().upper()
    print(f"\n{'='*70}")
    print(f"🔍 ĐANG PHÂN TÍCH CHI TIẾT MÃ CỔ PHIẾU: {symbol}")
    print(f"{'='*70}")

    df = screener.get_ticker_history(symbol, count=60)
    if df is None or len(df) < 30:
        print(f"❌ Không tìm thấy dữ liệu cho mã '{symbol}'. Vui lòng kiểm tra lại mã cổ phiếu!")
        return None

    item = {"stockSymbol": symbol}
    res = screener.analyze_stock(item, "HOSE/HNX")
    
    # Nếu analyze_stock trả về None do chưa đạt tiêu chuẩn khắt khe, ta vẫn tính toán đầy đủ để hiển thị hiện trạng của mã
    if res is None:
        screener.calculate_indicators(df)
        close = df['close'].iloc[-1]
        open_ = df['open'].iloc[-1]
        high = df['high'].iloc[-1]
        low = df['low'].iloc[-1]
        vol = df['volume'].iloc[-1]
        vol_ma20 = df['vol_ma20'].iloc[-1]
        vol_ratio = vol / vol_ma20 if vol_ma20 > 0 else 0
        change_pct = ((close - df['close'].iloc[-2]) / df['close'].iloc[-2]) * 100 if len(df) >= 2 else 0
        
        candle_range = high - low
        lower_wick = min(open_, close) - low
        lower_wick_ratio = lower_wick / candle_range if candle_range > 0 else 0

        st = df['supertrend'].iloc[-1]
        c_max = df['cloud_max'].iloc[-1]
        is_above_cloud = (c_max == c_max) and (close >= c_max * 0.99)

        recent_swing_low = df['low'].tail(10).min()
        sl = min(low * 0.99, recent_swing_low)
        risk = max(close - sl, close * 0.03)
        tp1 = close + risk * 1.0
        tp2 = close + risk * 2.0
        tp3 = close + risk * 3.0

        sl_pct = ((sl - close) / close) * 100
        tp1_pct = ((tp1 - close) / close) * 100
        tp2_pct = ((tp2 - close) / close) * 100
        tp3_pct = ((tp3 - close) / close) * 100

        is_whale = (vol_ratio >= 1.5) and (lower_wick_ratio >= 0.40)
        whale_badge = "🐋👑 [CÁ MẬP]" if is_whale else "📊 [THEO DÕI]"
        pattern = "Cá mập gom hàng" if is_whale else "Chưa có đột biến dòng tiền"
        win_rate = 88.0 if is_whale else 70.0

        res = {
            "symbol": symbol,
            "exchange": "HOSE/HNX",
            "price": close,
            "price_vnd": screener.format_vnd(close),
            "change_pct": change_pct,
            "volume": vol,
            "vol_ma20": vol_ma20,
            "vol_ratio": vol_ratio,
            "trade_value_bil": (close * 1000 * vol if close < 1000 else close * vol) / 1e9,
            "is_whale": is_whale,
            "whale_badge": whale_badge,
            "pattern": pattern,
            "win_rate": win_rate,
            "supertrend": "Tăng 🟢" if st == 1 else "Giảm 🔴",
            "sl": sl,
            "sl_vnd": screener.format_vnd(sl),
            "sl_pct": sl_pct,
            "tp1": tp1,
            "tp1_vnd": screener.format_vnd(tp1),
            "tp1_pct": tp1_pct,
            "tp2": tp2,
            "tp2_vnd": screener.format_vnd(tp2),
            "tp2_pct": tp2_pct,
            "tp3": tp3,
            "tp3_vnd": screener.format_vnd(tp3),
            "tp3_pct": tp3_pct
        }

    # In thông số chi tiết
    print(f"📊 Thông tin cơ bản: {res['symbol']} ({res['exchange']})")
    print(f"• Giá hiện tại: {res['price_vnd']} ({res['change_pct']:+.2f}%)")
    print(f"• Khối lượng phiên gần nhất: {int(res['volume']):,} cp (Gấp {res['vol_ratio']:.1f}x TB 20 phiên)")
    print(f"• Giá trị giao dịch: {res['trade_value_bil']:.1f} Tỷ VNĐ")
    print(f"• Xu hướng SuperTrend: {res['supertrend']}")
    print(f"• Trạng thái: {res['whale_badge']} [{res.get('win_rate', 80):.0f}%] - {res['pattern']}")
    print(f"-" * 50)
    print(f"🎯 Kế hoạch giao dịch đề xuất (Có tỷ lệ %):")
    print(f"• Điểm vào lệnh (Entry): {res['price_vnd']}")
    print(f"• Chốt lời TP1 (+1R):     {res['tp1_vnd']} ({res.get('tp1_pct', 0):+.1f}%) — Dời SL hòa vốn")
    print(f"• Chốt lời TP2 (+2R):     {res['tp2_vnd']} ({res.get('tp2_pct', 0):+.1f}%) — Mục tiêu chính")
    print(f"• Chốt lời TP3 (+3R):     {res['tp3_vnd']} ({res.get('tp3_pct', 0):+.1f}%) — Gồng lãi tối đa")
    print(f"• Cắt lỗ (SL):           {res['sl_vnd']} ({res.get('sl_pct', 0):+.1f}%)")
    print(f"{'='*70}\n")

    if send_telegram:
        print("[*] Đang gửi kết quả phân tích mã này sang Telegram của bạn...")
        sent = telegram_bot.send_telegram_alert(res, force=True, target_chat_id=target_chat_id)
        if sent:
            print(f"✅ Đã gửi phân tích mã {symbol} về Telegram thành công!")
        else:
            print("⚠️ Không gửi được Telegram (Vui lòng kiểm tra lại cài đặt).")

    return res

if __name__ == "__main__":
    if len(sys.argv) > 1:
        ticker = sys.argv[1]
    else:
        ticker = input("Nhập mã cổ phiếu bạn muốn xem (VD: HPG, SSI, VCB...): ").strip()
    
    if ticker:
        check_single_stock(ticker)
