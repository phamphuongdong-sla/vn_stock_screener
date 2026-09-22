# -*- coding: utf-8 -*-
"""
Module gửi tin nhắn cảnh báo tới Telegram (Giao diện Tinh gọn, Đẹp mắt, Súc tích)
"""
import requests
import config

def send_telegram_alert(signal_data: dict, force: bool = False) -> bool:
    """
    Gửi cảnh báo Telegram dạng Thẻ Card ProMax: Ngắn gọn, súc tích, đầy đủ tỷ lệ %
    """
    if not config.TELEGRAM_ENABLED:
        return False
    
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        return False

    win_rate = signal_data.get('win_rate', 0.0)
    
    # Lọc ngưỡng tối thiểu (mặc định 75%)
    if not force and win_rate < config.MIN_ALERT_WINRATE:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    symbol = signal_data.get('symbol', 'N/A')
    exchange = signal_data.get('exchange', 'HOSE')
    price_vnd = signal_data.get('price_vnd', '0 đ')
    change_pct = signal_data.get('change_pct', 0)
    vol_ratio = signal_data.get('vol_ratio', 0)
    trade_val_bil = signal_data.get('trade_value_bil', 0)
    pattern = signal_data.get('pattern', '')
    is_whale = signal_data.get('is_whale', False)
    
    sl_vnd = signal_data.get('sl_vnd', '0 đ')
    sl_pct = signal_data.get('sl_pct', 0)
    tp1_vnd = signal_data.get('tp1_vnd', '0 đ')
    tp1_pct = signal_data.get('tp1_pct', 0)
    tp2_vnd = signal_data.get('tp2_vnd', '0 đ')
    tp2_pct = signal_data.get('tp2_pct', 0)
    tp3_vnd = signal_data.get('tp3_vnd', '0 đ')
    tp3_pct = signal_data.get('tp3_pct', 0)

    icon_change = "🟢" if change_pct >= 0 else "🔴"

    # Rút gọn mô tả hành động giá cho tinh tế
    clean_pattern = pattern.replace("🐋 CÁ MẬP ", "").replace("Tín hiệu ", "")

    if is_whale:
        header = f"🐋👑 *{symbol}* — CÁ MẬP GOM HÀNG `[{win_rate:.0f}%]`"
    else:
        header = f"🚀 *{symbol}* — MUA TIÊU CHUẨN `[{win_rate:.0f}%]`"

    message = (
        f"{header}\n\n"
        f"💵 *Vào:* `{price_vnd}` ({icon_change} `{change_pct:+.2f}%`)\n"
        f"📊 *Vol:* `{vol_ratio:.1f}x` MA20 • *GTGD:* `{trade_val_bil:,.0f} Tỷ`\n"
        f"⚡️ *Tín hiệu:* {clean_pattern}\n\n"
        f"🎯 *TP1:* `{tp1_vnd}` (`{tp1_pct:+.1f}%`)\n"
        f"🎯 *TP2:* `{tp2_vnd}` (`{tp2_pct:+.1f}%`)\n"
        f"🎯 *TP3:* `{tp3_vnd}` (`{tp3_pct:+.1f}%`)\n"
        f"🛑 *SL:*  `{sl_vnd}` (`{sl_pct:+.1f}%`)"
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
