# -*- coding: utf-8 -*-
"""db.py — ذخیره تحلیل‌ها و واچ‌لیست در SQLite (فایل glm.db کنار برنامه)."""
import json
import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "glm.db")


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db():
    conn = get_db()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS analyses ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " created_at TEXT NOT NULL,"
            " symbol TEXT NOT NULL,"
            " score REAL,"
            " signal TEXT,"
            " raw_json TEXT)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at DESC)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS watchlist ("
            " symbol TEXT PRIMARY KEY,"
            " note TEXT,"
            " added_at TEXT NOT NULL)"
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- analyses
def save_analysis(symbol, result):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO analyses (created_at, symbol, score, signal, raw_json) VALUES (?,?,?,?,?)",
            (now, symbol, result.get("total_score"), result.get("signal"),
             json.dumps(result, ensure_ascii=False)),
        )
        conn.commit()
        return cur.lastrowid, now
    finally:
        conn.close()


def history(limit=30):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, created_at, symbol, score, signal FROM analyses ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_analysis(item_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT raw_json, symbol, created_at FROM analyses WHERE id=?",
                           (item_id,)).fetchone()
        if not row:
            return None
        data = json.loads(row["raw_json"])
        data["symbol"] = row["symbol"]
        data["created_at"] = row["created_at"]
        return data
    finally:
        conn.close()


def delete_analysis(item_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM analyses WHERE id=?", (item_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- watchlist
def watchlist():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT symbol, note, added_at FROM watchlist ORDER BY added_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def watchlist_symbols():
    return [row["symbol"] for row in watchlist()]


def watchlist_add(symbol, note=""):
    symbol = (symbol or "").strip()
    if not symbol:
        raise ValueError("نماد خالی است")
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO watchlist (symbol, note, added_at) VALUES (?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET note=excluded.note",
            (symbol, note.strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        conn.close()


def watchlist_remove(symbol):
    conn = get_db()
    try:
        conn.execute("DELETE FROM watchlist WHERE symbol=?", ((symbol or "").strip(),))
        conn.commit()
    finally:
        conn.close()


init_db()
