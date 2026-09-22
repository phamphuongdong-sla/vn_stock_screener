# -*- coding: utf-8 -*-
"""
Module gửi tin nhắn cảnh báo & Hướng dẫn sử dụng tới Telegram
Hỗ trợ cả chủ tài khoản và người ngoài tra cứu mã cổ phiếu
"""
import requests
import config

def send_welcome_help(target_chat_id: str) -> bool:
    """
    Gửi bảng hướng dẫn sử dụng chi tiết khi người dùng gõ /start hoặc /help
    """
    if not config.TELEGRAM_ENABLED:
        return False
        
    token = config.TELEGRAM_BOT_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    help_text = (
        "🐋👑 *BOT SOI CỔ PHIẾU CÁ MẬP (AI WHALE PROMAX)* 👑🐋\n"
        "────────────────────────\n"
        "Chào mừng bạn! Bot hỗ trợ phát hiện *Dấu Chân Cá Mập* gom hàng và tính toán kế hoạch giao dịch chuẩn xác cho TTCK Việt Nam.\n\n"
        "📖 *CÁCH TRA CỨU MÃ CỔ PHIẾU:*\n"
        "• *Cách 1:* Gõ trực tiếp mã cổ phiếu (VD: `HPG`, `SSI`, `VND`, `FPT`, `VCB`...)\n"
        "• *Cách 2:* Dùng lệnh `/soi <MÃ>` (VD: `/soi HPG` hoặc `/check SSI`)\n\n"
        "🎯 *BỘ THÔNG SỐ TRẢ VỀ:*\n"
        "✅ Trạng thái Dấu chân Cá Mập gom hàng / Quét thanh khoản\n"
        "✅ Xu hướng SuperTrend & Mây Ichimoku\n"
        "✅ Kế hoạch: Giá vào (Entry), Cắt lỗ (SL) & 3 mốc chốt lời TP1 (+1R), TP2 (+2R), TP3 (+3R) kèm tỷ lệ % rõ ràng!\n\n"
        "👉 _Hãy thử gõ ngay một mã như `HPG` hoặc `SSI` để xem kết quả!_"
    )
    
    payload = {
        "chat_id": target_chat_id,
        "text": help_text,
        "parse_mode": "Markdown"
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False

def send_telegram_alert(signal_data: dict, force: bool = False, target_chat_id: str = None) -> bool:
    """
    Gửi cảnh báo Telegram dạng Thẻ Card ProMax: Ngắn gọn, súc tích, đầy đủ tỷ lệ %
    Nếu target_chat_id được cung cấp, sẽ gửi trực tiếp cho người đó/nhóm đó.
    """
    if not config.TELEGRAM_ENABLED:
        return False
    
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = target_chat_id or config.TELEGRAM_CHAT_ID
    
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        return False

    has_buy_signal = signal_data.get('has_buy_signal', False)
    win_rate = signal_data.get('win_rate', 0.0)
    
    # Lọc quét tự động toàn sàn: Chỉ gửi khi CÓ ĐIỂM MUA và đạt win rate tối thiểu
    if not force:
        if not has_buy_signal or win_rate < config.MIN_ALERT_WINRATE:
            return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    symbol = signal_data.get('symbol', 'N/A')
    exchange = signal_data.get('exchange', 'HOSE')
    price_vnd = signal_data.get('price_vnd', '0 đ')
    change_pct = signal_data.get('change_pct', 0.0)
    vol_ratio = signal_data.get('vol_ratio', 0.0)
    projected_vol_ratio = signal_data.get('projected_vol_ratio', vol_ratio)
    trade_val_bil = signal_data.get('trade_value_bil', 0.0)
    pattern = signal_data.get('pattern', '')
    is_whale = signal_data.get('is_whale', False)
    is_at_ceiling = signal_data.get('is_at_ceiling', False)
    supertrend = signal_data.get('supertrend', 'N/A')
    cloud_status = signal_data.get('cloud_status', 'N/A')
    candle_date = signal_data.get('candle_date', '')
    updated_time = signal_data.get('updated_time', '')
    recommendation = signal_data.get('recommendation', '')
    
    sl_vnd = signal_data.get('sl_vnd', '0 đ')
    sl_pct = signal_data.get('sl_pct', 0.0)
    tp1_vnd = signal_data.get('tp1_vnd', '0 đ')
    tp1_pct = signal_data.get('tp1_pct', 0.0)
    tp2_vnd = signal_data.get('tp2_vnd', '0 đ')
    tp2_pct = signal_data.get('tp2_pct', 0.0)
    tp3_vnd = signal_data.get('tp3_vnd', '0 đ')
    tp3_pct = signal_data.get('tp3_pct', 0.0)

    icon_change = "🟢" if change_pct >= 0 else "🔴"
    clean_pattern = pattern.replace("🐋 CÁ MẬP ", "").replace("Tín hiệu ", "")

    time_str = f"`{updated_time}` (Nến `{candle_date}`)" if candle_date else f"`{updated_time}`"
    
    vol_str = f"`{vol_ratio:.1f}x` MA20"
    if projected_vol_ratio > vol_ratio and projected_vol_ratio >= 1.2:
        vol_str += f" (Dự phóng: `{projected_vol_ratio:.1f}x`)"

    ceiling_line = "\n⚠️ *CẢNH BÁO:* _Giá đã sát trần! Không mua đuổi (FOMO)._\n" if is_at_ceiling else ""

    if has_buy_signal:
        badge_name = "🐋👑 CÁ MẬP GOM HÀNG" if is_whale else "🚀 BỨT PHÁ (SOS BREAKOUT)"
        message = (
            f"🔥 *{symbol}* — CÓ ĐIỂM MUA THEO CHỈ BÁO `[{win_rate:.0f}%]`\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ *Thời gian:* {time_str}\n"
            f"🏢 *Sàn:* `{exchange}` • *Thị giá:* `{price_vnd}` ({icon_change} `{change_pct:+.2f}%`)\n\n"
            f"📊 *Khối lượng:* {vol_str}\n"
            f"💰 *Giá trị GD:* `{trade_val_bil:,.1f} Tỷ VNĐ`\n"
            f"⚡️ *Dấu chân:* {badge_name}\n"
            f"📈 *Hợp lưu:* SuperTrend {supertrend} • {cloud_status}{ceiling_line}\n"
            f"───────────────────\n"
            f"🎯 *KẾ HOẠCH GIAO DỊCH (R:R CHUẨN)*\n"
            f"• 🎯 *TP1 (+1R):* `{tp1_vnd}` (`{tp1_pct:+.1f}%`) — _Dời SL hòa vốn_\n"
            f"• 🎯 *TP2 (+2R):* `{tp2_vnd}` (`{tp2_pct:+.1f}%`) — _Mục tiêu chính_\n"
            f"• 🎯 *TP3 (+3R):* `{tp3_vnd}` (`{tp3_pct:+.1f}%`) — _Gồng lãi tối đa_\n"
            f"• 🛑 *SL:*       `{sl_vnd}` (`{sl_pct:+.1f}%`)\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💡 _Quản trị rủi ro: Tối đa 2% NAV cho mỗi vị thế!_"
        )
    else:
        message = (
            f"⚪️ *{symbol}* — CHƯA CÓ ĐIỂM MUA `[{win_rate:.0f}%]`\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ *Thời gian:* {time_str}\n"
            f"🏢 *Sàn:* `{exchange}` • *Thị giá:* `{price_vnd}` ({icon_change} `{change_pct:+.2f}%`)\n\n"
            f"📊 *Khối lượng:* {vol_str}\n"
            f"💰 *Giá trị GD:* `{trade_val_bil:,.1f} Tỷ VNĐ`\n"
            f"📈 *SuperTrend:* {supertrend}\n"
            f"☁️ *Mây Ichimoku:* {cloud_status}\n"
            f"⚡️ *Dòng tiền:* {clean_pattern}\n"
            f"───────────────────\n"
            f"👉 *Khuyến nghị:* {recommendation}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔍 _Bot sẽ tự động cảnh báo khi mã kích hoạt điểm mua chuẩn!_"
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
