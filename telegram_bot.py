# -*- coding: utf-8 -*-
"""
Module gửi tin nhắn cảnh báo tới Telegram (Định dạng ProMax đầy đủ tỷ lệ %)
"""
import requests
import config

def send_telegram_alert(signal_data: dict) -> bool:
    """
    Gửi cảnh báo phát hiện cổ phiếu có dòng tiền cá mập về Telegram
    Bao gồm đầy đủ tỷ lệ % WinRate và % Lợi nhuận/Cắt lỗ như trên chỉ báo Pine Script
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
    win_rate = signal_data.get('win_rate', 80.0)
    
    sl_vnd = signal_data.get('sl_vnd', '0 đ')
    sl_pct = signal_data.get('sl_pct', -5.0)
    tp1_vnd = signal_data.get('tp1_vnd', '0 đ')
    tp1_pct = signal_data.get('tp1_pct', 5.0)
    tp2_vnd = signal_data.get('tp2_vnd', '0 đ')
    tp2_pct = signal_data.get('tp2_pct', 10.0)
    tp3_vnd = signal_data.get('tp3_vnd', '0 đ')
    tp3_pct = signal_data.get('tp3_pct', 15.0)

    icon_change = "🟢" if change_pct >= 0 else "🔴"

    if is_whale:
        header = f"🐋👑 *CÁ MẬP GOM HÀNG [{win_rate:.0f}%]* 👑🐋\n🔥 *Mã Cổ Phiếu:* `{symbol}` ({exchange})"
    else:
        header = f"🚀 *TÍN HIỆU MUA TIÊU CHUẨN [{win_rate:.0f}%]*\n🔥 *Mã:* `{symbol}` ({exchange})"

    message = (
        f"{header}\n"
        f"────────────────────────\n"
        f"🏷 *Phân Loại:* `{whale_badge}`\n"
        f"📈 *Hành Vi Giá:* *{pattern}*\n"
        f"🧠 *Độ Tin Cậy AI:* `{win_rate:.0f}%`\n\n"
        f"📊 *Thông Số Dòng Tiền:*\n"
        f"• Giá hiện tại: `{price_vnd}` ({icon_change} `{change_pct:+.2f}%`)\n"
        f"• Giá trị GD: `{trade_val_bil:,.1f}` Tỷ VNĐ\n"
        f"• Khối lượng: `{vol_current:,.0f}` (Gấp `{vol_ratio:.1f}x` TB 20 phiên)\n\n"
        f"🎯 *Kế Hoạch Giao Dịch Đề Xuất (VNĐ & %):*\n"
        f"• 💰 Điểm vào (Entry): `{price_vnd}`\n"
        f"• 🎯 TP1 (+1R): `{tp1_vnd}` (`{tp1_pct:+.1f}%`) — _Dời SL hòa vốn_\n"
        f"• 🎯 TP2 (+2R): `{tp2_vnd}` (`{tp2_pct:+.1f}%`) — _Chốt lời mục tiêu_\n"
        f"• 🎯 TP3 (+3R): `{tp3_vnd}` (`{tp3_pct:+.1f}%`) — _Gồng lãi tối đa_\n"
        f"• 🛑 Cắt lỗ (SL): `{sl_vnd}` (`{sl_pct:+.1f}%`) — _Dưới chân nến_\n\n"
        f"⏱ _Đồng bộ 100% với Thẻ Card chỉ báo AI Whale ProMax._"
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
