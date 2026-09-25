# -*- coding: utf-8 -*-
"""
database.py — Quản lý SQLite Database lưu trữ tín hiệu và sự kiện của Bot.
Đáp ứng chuẩn Section 16 & 11:
- Lưu trữ signals: id, symbol, timestamp, timeframe, signal, strength, entry, sl, tp1, tp2, atr, stock_trend, trend_d, trend_w, vnindex_trend, market_relation, status, result
- Lưu trữ bot_events: timestamp, level, event, message
- Chống gửi trùng tín hiệu bằng Unique Key: symbol + timeframe + timestamp + signal
"""

import os
import sqlite3
from datetime import datetime
from typing import Optional, Dict, List

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DB_DIR, "bot_data.db")


def get_connection():
    """Tạo kết nối SQLite an toàn với timeout và WAL mode."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    """Khởi tạo cấu trúc các bảng nếu chưa có."""
    with get_connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            timeframe TEXT NOT NULL DEFAULT '1D',
            signal TEXT NOT NULL,
            strength TEXT NOT NULL,
            entry REAL NOT NULL,
            sl REAL NOT NULL,
            tp1 REAL NOT NULL,
            tp2 REAL NOT NULL,
            atr REAL NOT NULL,
            stock_trend TEXT NOT NULL,
            trend_d TEXT NOT NULL,
            trend_w TEXT NOT NULL,
            vnindex_trend TEXT NOT NULL,
            market_relation TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            result TEXT DEFAULT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(symbol, timeframe, timestamp, signal)
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            level TEXT NOT NULL,
            event TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        conn.commit()


def is_signal_exists(symbol: str, timeframe: str, timestamp: int, signal: str) -> bool:
    """Kiểm tra tín hiệu đã từng được lưu hay chưa để chống gửi trùng tuyệt đối."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 1 FROM signals 
            WHERE symbol = ? AND timeframe = ? AND timestamp = ? AND signal = ?
            LIMIT 1;
        """, (symbol.upper(), timeframe, int(timestamp), signal))
        return cursor.fetchone() is not None


def save_signal(data: dict) -> bool:
    """
    Lưu một tín hiệu mới vào database.
    Trả về True nếu lưu thành công, False nếu đã tồn tại (duplicate).
    """
    now_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_ts = int(data.get("timestamp") or datetime.now().timestamp())
    symbol = str(data.get("symbol", "")).upper()
    timeframe = str(data.get("timeframe", "1D"))
    signal = str(data.get("signal", "BUY"))

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO signals (
                    symbol, timestamp, timeframe, signal, strength,
                    entry, sl, tp1, tp2, atr,
                    stock_trend, trend_d, trend_w, vnindex_trend, market_relation,
                    status, result, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol,
                now_ts,
                timeframe,
                signal,
                str(data.get("strength", "STANDARD")),
                float(data.get("entry", 0.0)),
                float(data.get("sl", 0.0)),
                float(data.get("tp1", 0.0)),
                float(data.get("tp2", 0.0)),
                float(data.get("atr", 0.0)),
                str(data.get("stock_trend", "TĂNG")),
                str(data.get("trend_d", "TĂNG")),
                str(data.get("trend_w", "TĂNG")),
                str(data.get("vnindex_trend", "NGANG")),
                str(data.get("market_relation", "ĐỒNG PHA")),
                str(data.get("status", "ACTIVE")),
                data.get("result"),
                now_dt,
            ))
            conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        log_event("ERROR", "SAVE_SIGNAL_FAIL", f"Lỗi lưu tín hiệu {symbol}: {e}")
        return False


def log_event(level: str, event: str, message: str):
    """Ghi nhật ký sự kiện hệ thống vào bot_events."""
    now_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_ts = int(datetime.now().timestamp())
    try:
        with get_connection() as conn:
            conn.execute("""
                INSERT INTO bot_events (timestamp, level, event, message, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (now_ts, level.upper(), event, message, now_dt))
            conn.commit()
    except Exception:
        pass


def get_recent_signals(symbol: Optional[str] = None, limit: int = 20) -> List[Dict]:
    """Lấy danh sách các tín hiệu gần nhất từ database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if symbol:
            cursor.execute("""
                SELECT * FROM signals WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?;
            """, (symbol.upper(), limit))
        else:
            cursor.execute("""
                SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?;
            """, (limit,))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

# Khởi tạo db ngay khi import
init_db()
