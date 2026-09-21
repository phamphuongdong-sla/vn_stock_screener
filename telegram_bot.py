# -*- coding: utf-8 -*-
"""
Module gửi tin nhắn cảnh báo tới Telegram (Định dạng VNĐ ProMax)
"""
import requests
import config

def send_telegram_alert(signal_data: dict) -> bool:
    """
    Gửi cảnh báo phát hiện cổ phiếu có dòng tiền cá mập về Telegram
    """
    if not config.TELEGRAM_ENABLED:
        return False
    
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    symbol = signal_data.get('symbol', 'N/A')
    exchange = signal_data.get('exchange', 'HOSE')
    price_vnd = signal_data.get('price_vnd', '0 đ')
    change_pct = signal_data.get('change_pct', 0)
    vol_current = signal_data.get('volume', 0)
    vol_ratio = signal_data.get('vol_ratio', 0)
    trade_val_bil = signal_data.get('trade_value_bil', 0)
    pattern = signal_data.get('pattern', '')
    is_whale = signal_data.get('is_whale', False)
    whale_badge = signal_data.get('whale_badge', '')
    
    sl_vnd = signal_data.get('sl_vnd', '0 đ')
    tp1_vnd = signal_data.get('tp1_vnd', '0 đ')
    tp2_vnd = signal_data.get('tp2_vnd', '0 đ')
    tp3_vnd = signal_data.get('tp3_vnd', '0 đ')

    icon_change = "🟢" if change_pct >= 0 else "🔴"

    if is_whale:
        header = f"🐋👑 *XÁC NHẬN CHẮC CHẮN CÓ CÁ MẬP (SMART MONEY)* 👑🐋\n🔥 *Mã:* `{symbol}` ({exchange})"
    else:
        header = f"📊 *TÍN HIỆU TIÊU CHUẨN — {symbol} ({exchange})*"

    message = (
        f"{header}\n\n"
        f"🏷 *Phân Loại:* `{whale_badge}`\n"
        f"📈 *Hành Vi Giá:* *{pattern}*\n\n"
        f"📊 *Thông Số Dòng Tiền:*\n"
        f"• Giá hiện tại: `{price_vnd}` ({icon_change} `{change_pct:+.2f}%`)\n"
        f"• Giá trị GD: `{trade_val_bil:,.1f}` Tỷ VNĐ\n"
        f"• Khối lượng: `{vol_current:,.0f}` (Gấp `{vol_ratio:.1f}x` TB 20 phiên)\n\n"
        f"🎯 *Kế Hoạch Giao Dịch Đề Xuất (VNĐ):*\n"
        f"• 💰 Điểm vào (Entry): `{price_vnd}`\n"
        f"• 🛑 Cắt lỗ (SL): `{sl_vnd}`\n"
        f"• 🎯 TP1 (R:R 1:1): `{tp1_vnd}` (+1R — Dời SL hòa vốn)\n"
        f"• 🎯 TP2 (R:R 1:2): `{tp2_vnd}` (+2R)\n"
        f"• 🎯 TP3 (R:R 1:3): `{tp3_vnd}` (+3R — Chốt toàn bộ)\n\n"
        f"⏱ _Hệ thống đồng bộ trực tiếp với chỉ báo AI Whale ProMax._"
    )

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"[Lỗi Telegram] {e}")
        return False
