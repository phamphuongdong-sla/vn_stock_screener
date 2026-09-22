# -*- coding: utf-8 -*-
"""
Script soi chi tiết 1 mã cổ phiếu bất kỳ
Cách dùng:
  ./venv/bin/python3 check.py HPG
  ./venv/bin/python3 check.py SSI
  (hoặc chạy python3 check.py rồi nhập mã)
"""

import sys
import time
import pandas as pd
import numpy as np
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

    # Lấy dữ liệu thời gian thực từ bảng giá
    item = screener.get_live_stock_quote(symbol)
    exchange = item.get("exchange_name", "HOSE/HNX")
    res = screener.analyze_stock(item, exchange)
    
    from datetime import datetime
    in_session = main.is_trading_hour()
    now_str = datetime.now().strftime("%H:%M %d/%m/%Y")
    candle_ts = df['time'].iloc[-1] if 'time' in df.columns else None
    last_candle_date = datetime.fromtimestamp(int(candle_ts)).strftime("%d/%m/%Y") if candle_ts else datetime.now().strftime("%d/%m/%Y")

    if in_session:
        time_display = f"{now_str} (Thời gian thực)"
        session_tag = "Thời gian thực"
    else:
        time_display = f"{now_str} (Chốt phiên {last_candle_date})"
        session_tag = f"Chốt phiên {last_candle_date}"

    # Nếu analyze_stock trả về None do chưa có điểm mua mới, ta tính toán hiện trạng bảng HUD chuẩn xác
    if res is None:
        raw_price = (
            item.get("matchedPrice") or 
            item.get("lastPrice") or 
            item.get("expectedMatchedPrice") or 
            item.get("close", 0)
        )
        raw_vol = (
            item.get("nmTotalTradedQty") or 
            item.get("stockVol") or 
            item.get("totalVol") or 
            item.get("expectedMatchedVolume", 0)
        )

        if not raw_price or float(raw_price) <= 0:
            close = df['close'].iloc[-1]
            vol = float(df['volume'].iloc[-1])
            open_ = df['open'].iloc[-1]
            high = df['high'].iloc[-1]
            low = df['low'].iloc[-1]
            change_pct = ((close - df['close'].iloc[-2]) / df['close'].iloc[-2]) * 100.0 if len(df) >= 2 else 0.0
            df_eval = df.copy()
        else:
            close = screener.normalize_price_k(raw_price)
            vol = float(raw_vol) if raw_vol and float(raw_vol) > 0 else float(df['volume'].iloc[-1])
            open_ = screener.normalize_price_k(item.get("openPrice") or item.get("open")) or close
            high = screener.normalize_price_k(item.get("highest") or item.get("highestPrice") or item.get("high")) or max(close, open_)
            low = screener.normalize_price_k(item.get("lowest") or item.get("lowestPrice") or item.get("low")) or min(close, open_)
            high = max(high, close, open_)
            low = min(low, close, open_)

            change_pct = float(
                item.get("priceChangePercent") or 
                item.get("changePercent") or 
                item.get("matchedPricePercent") or 
                item.get("expectedPriceChangePercent") or 0.0
            )
            if change_pct == 0.0 and len(df) >= 2 and df['close'].iloc[-2] > 0:
                change_pct = ((close - df['close'].iloc[-2]) / df['close'].iloc[-2]) * 100.0

            import time
            today_row = pd.DataFrame([{
                'time': int(time.time()),
                'open': open_,
                'high': high,
                'low': low,
                'close': close,
                'volume': vol
            }])
            df_eval = pd.concat([df, today_row], ignore_index=True)

        screener.calculate_indicators(df_eval)

        vol_ma20 = float(df_eval['vol_ma20'].iloc[-1])
        vol_ratio = vol / vol_ma20 if vol_ma20 > 0 else 0.0
        
        st = df_eval['supertrend'].iloc[-1]
        c_max = df_eval['cloud_max'].iloc[-1]
        is_above_cloud = pd.notna(c_max) and (close >= c_max * 0.99)
        cloud_status = "Trên Mây 🟢" if is_above_cloud else "Dưới Mây 🔴"
        is_supertrend_bull = (st == 1)
        current_trend = df_eval['trend'].iloc[-1]

        # HUD Xu hướng chuẩn Pine Script
        if current_trend == 4:
            hud_trend = "TĂNG MẠNH 🟢"
        elif current_trend == -4:
            hud_trend = "GIẢM MẠNH 🔴"
        else:
            hud_trend = "SIDEWAY ⚪"

        elapsed_mins = screener.get_elapsed_trading_minutes()
        if elapsed_mins < 270 and vol > 0 and elapsed_mins >= 30:
            projected_vol = (vol / elapsed_mins) * 270.0
            projected_vol_ratio = projected_vol / vol_ma20 if vol_ma20 > 0 else 0.0
        else:
            projected_vol = vol
            projected_vol_ratio = vol_ratio

        # HUD Dòng tiền chuẩn Pine Script
        is_ultra_vol = (vol_ratio >= 1.3) or (elapsed_mins >= 45 and vol_ratio >= 0.7 and projected_vol_ratio >= 1.5)
        hud_money = "🐋 CÁ MẬP VÀO" if is_ultra_vol else "Bình Thường ⏳"
        hud_order = f"MUA tại {screener.format_vnd(close)} (SL: {screener.format_vnd(sl)})" if has_buy_signal else "Đang Chờ... ⏸"

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

        # Đánh giá đúng theo chỉ báo: Có điểm mua hay chưa có điểm mua
        has_buy_signal = False
        if current_trend == 4:
            status_label = "CHƯA CÓ ĐIỂM MUA MỚI"
            recommendation = "Cổ phiếu đang giữ xu hướng TĂNG MẠNH 🟢 & Trên Mây nhưng chưa xuất hiện điểm gom / bùng nổ mới hôm nay (Lệnh Mở: Đang Chờ... ⏸). Ưu tiên quan sát hoặc nắm giữ vị thế cũ."
            whale_badge = "📈 [TĂNG MẠNH]"
            pattern = "Xu hướng tăng mạnh (Lệnh Mở: Đang Chờ... ⏸)"
            win_rate = 70.0
        elif current_trend == -4:
            status_label = "CHƯA CÓ ĐIỂM MUA"
            recommendation = "Cổ phiếu đang xu hướng GIẢM MẠNH 🔴 & Dưới Mây Ichimoku. Tuyệt đối không bắt đáy, đứng ngoài quan sát."
            whale_badge = "🛑 [XU HƯỚNG GIẢM]"
            pattern = "Xu hướng giảm (Đang Chờ... ⏸)"
            win_rate = 45.0
        else:
            status_label = "CHƯA CÓ ĐIỂM MUA"
            recommendation = "Cổ phiếu đang đi ngang (SIDEWAY ⚪). Chưa có dòng tiền bứt phá, tiếp tục quan sát."
            whale_badge = "⚪️ [SIDEWAY]"
            pattern = "Đi ngang tích lũy (Đang Chờ... ⏸)"
            win_rate = 55.0

        res = {
            "symbol": symbol,
            "exchange": exchange,
            "price": close,
            "price_vnd": screener.format_vnd(close),
            "change_pct": change_pct,
            "volume": vol,
            "vol_ma20": vol_ma20,
            "vol_ratio": vol_ratio,
            "projected_vol": projected_vol,
            "projected_vol_ratio": projected_vol_ratio,
            "trade_value_bil": (close * 1000 * vol if close < 1000 else close * vol) / 1e9,
            "is_whale": is_ultra_vol,
            "whale_badge": whale_badge,
            "pattern": pattern,
            "win_rate": win_rate,
            "supertrend": "Tăng 🟢" if is_supertrend_bull else "Giảm 🔴",
            "cloud_status": cloud_status,
            "hud_trend": hud_trend,
            "hud_money": hud_money,
            "hud_order": hud_order,
            "has_buy_signal": False,
            "status_label": status_label,
            "recommendation": recommendation,
            "candle_date": last_candle_date,
            "updated_time": now_str,
            "time_display": time_display,
            "session_tag": session_tag,
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
    else:
        # Nếu analyze_stock đã lọc ra (đạt chuẩn chỉ báo)
        res["has_buy_signal"] = True
        res["candle_date"] = last_candle_date
        res["updated_time"] = now_str
        res["time_display"] = time_display
        res["session_tag"] = session_tag

    # In thông số chi tiết chuẩn bảng HUD TradingView
    print(f"📊 Thông tin cơ bản: {res['symbol']} ({res['exchange']})")
    print(f"• Thời gian: {res.get('time_display', '')}")
    print(f"• Giá hiện tại: {res['price_vnd']} ({res['change_pct']:+.2f}%)")
    print(f"• Khối lượng: {int(res['volume']):,} cp (Gấp {res['vol_ratio']:.1f}x TB 20 phiên)")
    print(f"• Giá trị giao dịch: {res['trade_value_bil']:.1f} Tỷ VNĐ")
    print(f"• Xu hướng: {res.get('hud_trend', res.get('supertrend'))} ({res.get('cloud_status', 'N/A')})")
    print(f"• Dòng tiền: {res.get('hud_money', 'Bình Thường ⏳')}")
    print(f"• Lệnh mở: {res.get('hud_order', 'Đang Chờ... ⏸')}")
    print(f"• Trạng thái chỉ báo: {'🟢 CÓ ĐIỂM MUA' if res.get('has_buy_signal') else '⚪️ CHƯA CÓ ĐIỂM MUA'} [{res.get('win_rate', 70):.0f}%]")
    print(f"• Khuyến nghị: {res.get('recommendation', '')}")

    if res.get('has_buy_signal'):
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
