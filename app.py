# -*- coding: utf-8 -*-
"""app.py — «GLM Bourse» سیستم ۴ ایجنته امتیازدهی بورس ایران.

ایجنت‌ها (به ترتیب اجرا):
  ۱. Collector  — جمع‌آوری دیتای زنده TSETMC + اعتبارسنجی تازگی
  ۲. Processor  — محاسبه اندیکاتورها + امتیاز ۰-۱۰۰ برای هر پارامتر وزنی
  ۳. Tactician  — نقاط تاکتیکی (ورود/حد ضرر/اهداف/ریسک-بازده/اندازه موقعیت)
  ۴. Announcer  — امتیاز کل وزنی → سیگنال خرید/فروش/نگهداری/نظاره + دلایل

هر تحلیل در SQLite ذخیره می‌شود. وزن‌ها از config.json خوانده و از UI قابل‌تغییرند.

اجرا:  python app.py   →  http://127.0.0.1:5001
"""
import logging
import os
import re
import subprocess
import time

from flask import Flask, jsonify, render_template, request

import scoring
import db
from agents.base import AgentError
from agents import tsetmc_client as tsetmc
from agents.collector import CollectorAgent
from agents.processor import ProcessorAgent
from agents.tactician import TacticianAgent
from agents.announcer import AnnouncerAgent

request_utils = __import__("requests").utils

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "glm.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("glm")

app = Flask(__name__)
app.json.ensure_ascii = False


def run_pipeline(symbol):
    """هر چهار ایجنت را پشت‌سرهم روی یک نماد اجرا می‌کند."""
    cfg = scoring.load_config()
    context = {"symbol": symbol}
    agents = [
        CollectorAgent(),
        ProcessorAgent(),
        TacticianAgent(cfg),
        AnnouncerAgent(cfg),
    ]
    trail = []
    for agent in agents:
        out = agent.run(context)
        trail.append({"agent": agent.name, "title": agent.title,
                      "elapsed_sec": out.get("elapsed_sec")})

    scores = context.get("scores", {})
    weights = scoring.normalize_weights(cfg.get("weights", {}))
    components = []
    for key, data in scores.items():
        components.append({
            "key": key,
            "label": scoring.COMPONENT_LABELS.get(key, key),
            "score": (round(data["score"], 1) if data.get("score") is not None else None),
            "value": data.get("value"),
            "reason": data.get("reason"),
            "weight": round(weights.get(key, 0.0) * 100, 1),
        })

    final = context.get("final", {})
    result = {
        "symbol": symbol,
        "total_score": final.get("total_score"),
        "signal": final.get("signal"),
        "summary": final.get("summary"),
        "reasons": final.get("reasons"),
        "risks": final.get("risks"),
        "disclaimer": final.get("disclaimer"),
        "components": components,
        "tactics": context.get("tactics"),
        "agent_trail": trail,
    }
    return result


# ---------------------------------------------------------------------- نماد
def _clean_search_rows(raw):
    """صف کاندیدهای جستجو را فیلتر و مرتب می‌کند (فقط سهام، بدون اختیار/قرارداد)."""
    rows = [r for r in (raw or []) if isinstance(r, dict) and r.get("insCode")]
    out = []
    for r in rows:
        tiker = str(r.get("lVal18AFC") or "").strip()
        name = str(r.get("lVal30") or "").strip()
        # اختیار معامله/حق تقدم از نام مشخص است؛ از لیست پیشنهاد حذف می‌کنیم
        if any(k in name or k in tiker for k in ("اختیار", "حق تقدم", "اتص", "سلام")):
            continue
        out.append({
            "ins_code": str(r.get("insCode")),
            "ticker": tiker,
            "name": name,
        })
    return out[:10]


_ISIN_RE = re.compile(r"^(IR[A-Z0-9]{10}|IRO[0-9A-Z]{8,12})$")


def _isin_to_ticker(isin):
    """تبدیل ISIN (مثل IRO3PAIP0001 از EasyTrader) به نماد فارسی.

    از دیتای MarketWatchPlus سایت TSETMC (دیکشنری کل بازار) استفاده می‌کند و
    نتیجه را ۱ ساعت کش می‌کند. اگر ISIN پیدا نشد None برمی‌گردد.
    """
    now = time.time()
    if _isin_cache["ts"] and now - _isin_cache["ts"] < 3600 and _isin_cache["map"]:
        return _isin_cache["map"].get(isin)
    try:
        # نکته: requests به old.tsetmc.com به‌دلیل ناسازگاری TLS/HTTP2 تایم‌اوت می‌شود،
        # ولی curl مستقیم کار می‌کند — پس از subprocess استفاده می‌کنیم.
        r = subprocess.run(
            ["curl", "-s", "--noproxy", "*", "--compressed", "--max-time", "25",
             "https://old.tsetmc.com/tsev2/data/MarketWatchPlus.aspx",
             "-H", "User-Agent: Mozilla/5.0"],
            capture_output=True, timeout=30,
        )
        if r.returncode != 0 or not r.stdout:
            raise OSError("curl exit %d" % r.returncode)
        txt = r.stdout.decode("utf-8", errors="ignore")
        mapping = {}
        for m in re.finditer(r"([A-Z0-9]{12}),(IRO[0-9A-Z]{8,12}),([^,@;\r\n]+),([^,@;\r\n]+),", txt):
            key = m.group(2)
            if key not in mapping:
                mapping[key] = m.group(3).strip()
        if len(mapping) < 100:
            log.warning("دیتای MarketWatchPlus ناقص بود (%d نماد) — کش دور زده شد", len(mapping))
            return _isin_cache["map"].get(isin) if _isin_cache["map"] else None
        _isin_cache["map"] = mapping
        _isin_cache["ts"] = now
        log.info("دیکشنری ISIN→نماد ساخته شد: %d نماد", len(mapping))
        return mapping.get(isin)
    except Exception as exc:
        log.warning("ساخت دیکشنری ISIN ناموفق: %s", exc)
        return _isin_cache["map"].get(isin) if _isin_cache["map"] else None


_isin_cache = {"map": {}, "ts": 0.0}


def _resolve_symbols_bulk(text):
    """ورودی آزاد کاربر را می‌گیرد: نماد فارسی، ISIN، یا لینک EasyTrader.
    خروجی: (لیست نماد، لیست خطاها)"""
    resolved, errors = [], []
    for token in re.split(r"[,،\n\s]+", (text or "").strip()):
        if not token:
            continue
        # لینک EasyTrader: https://d.easytrader.ir/easy-chart/IRO3PAIP0001
        m = re.search(r"easy-chart/([A-Z0-9]{12})", token)
        isin = None
        if m:
            isin = m.group(1)
        elif _ISIN_RE.match(token):
            isin = token
        if isin:
            ticker = _isin_to_ticker(isin)
            if ticker:
                resolved.append(ticker)
            else:
                errors.append("%s: ISIN در TSETMC پیدا نشد." % isin)
        else:
            resolved.append(token)
    return resolved, errors


@app.get("/api/search/<path:query>")
def api_search(query):
    """جستجوی زنده نماد در TSETMC برای autocomplete فیلد ورودی.
    اگر ورودی ISIN باشد، مستقیم به نماد تبدیل می‌شود."""
    query = (query or "").strip()
    if len(query) < 2:
        return jsonify(ok=True, results=[])
    m = re.search(r"([A-Z0-9]{12})", query)
    if m and _ISIN_RE.match(m.group(1)):
        ticker = _isin_to_ticker(m.group(1))
        if ticker:
            return jsonify(ok=True, results=[{
                "ins_code": "", "ticker": ticker, "name": "از ISIN: " + m.group(1),
            }])
    try:
        data = tsetmc._get(tsetmc.BASE + "/api/Instrument/GetInstrumentSearch/" +
                           request_utils.quote(query))
        return jsonify(ok=True, results=_clean_search_rows(data.get("instrumentSearch")))
    except Exception as exc:
        log.warning("جستجوی نماد ناموفق: %s", exc)
        return jsonify(ok=True, results=[])


# ---------------------------------------------------------------------- watchlist
@app.get("/api/watchlist")
def api_watchlist():
    conn_symbols = db.watchlist_symbols()
    return jsonify(ok=True, data=db.watchlist(), symbols=", ".join(conn_symbols))


@app.post("/api/watchlist")
def api_watchlist_add():
    data = request.get_json(silent=True) or {}
    symbol = (data.get("symbol") or "").strip()
    if not symbol:
        return jsonify(ok=False, error="نام نماد را وارد کنید."), 400
    # ورودی می‌تواند چند نماد/ISIN/لینک EasyTrader باشد
    resolved, errors = _resolve_symbols_bulk(symbol)
    added = []
    try:
        for sym in resolved:
            db.watchlist_add(sym, data.get("note") or "")
            added.append(sym)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    if errors:
        return jsonify(ok=True, data=db.watchlist(),
                       warning="این موارد اضافه نشدند: " + "؛ ".join(errors))
    return jsonify(ok=True, data=db.watchlist(), added=added)


@app.delete("/api/watchlist/<path:symbol>")
def api_watchlist_delete(symbol):
    db.watchlist_remove(symbol)
    return jsonify(ok=True, data=db.watchlist())


@app.post("/api/watchlist/scan")
def api_watchlist_scan():
    """همه نمادهای واچ‌لیست را تحلیل و مقایسه با سیگنال قبلی هر نماد می‌کند."""
    symbols = db.watchlist_symbols()
    if not symbols:
        return jsonify(ok=False, error="واچ‌لیست خالی است."), 400

    # آخرین سیگنال ثبت‌شده هر نماد (قبل از این اسکن) برای تشخیص تغییر سیگنال
    prev = {}
    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT symbol, signal FROM analyses WHERE id IN "
            "(SELECT MAX(id) FROM analyses GROUP BY symbol)"
        ).fetchall()
        for r in rows:
            prev[r["symbol"]] = r["signal"]
    finally:
        conn.close()

    results, errors = [], []
    for sym in symbols:
        try:
            result = run_pipeline(sym)
            rid, created = db.save_analysis(sym, result)
            result["id"] = rid
            result["created_at"] = created
            result["prev_signal"] = prev.get(sym)
            results.append(result)
        except AgentError as exc:
            errors.append("%s: %s" % (sym, exc))
        except Exception as exc:
            log.exception("خطای غیرمنتظره در اسکن %s", sym)
            errors.append("%s: خطای داخلی (%s)" % (sym, exc))

    return jsonify(ok=True, results=results, errors=errors, scanned=len(results))


# ---------------------------------------------------------------------- routes
@app.get("/api/health")
def health():
    return jsonify(ok=True, status="up", app="GLM Bourse")


@app.get("/")
def index():
    cfg = scoring.load_config()
    return render_template("index.html",
                           default_symbols=", ".join(cfg.get("default_symbols", [])),
                           weights=scoring.normalize_weights(cfg.get("weights", {})),
                           labels=scoring.COMPONENT_LABELS,
                           thresholds=cfg.get("thresholds", {}),
                           risk_pct=cfg.get("max_risk_per_trade_pct", 5),
                           watchlist=db.watchlist())


@app.post("/api/analyze")
def api_analyze():
    data = request.get_json(silent=True) or {}
    symbols_raw = (data.get("symbols") or "").strip()
    if not symbols_raw:
        return jsonify(ok=False, error="حداقل یک نماد وارد کنید."), 400
    # ورودی آزاد: نماد فارسی، ISIN، یا لینک EasyTrader (حداکثر ۲۰ نماد)
    symbols, isin_errors = _resolve_symbols_bulk(symbols_raw)
    symbols = symbols[:20]
    if not symbols:
        return jsonify(ok=False, error="نام نماد معتبر نیست.",
                       errors=isin_errors), 400

    results, errors = [], []
    for sym in symbols:
        try:
            result = run_pipeline(sym)
            rid, created = db.save_analysis(sym, result)
            result["id"] = rid
            result["created_at"] = created
            results.append(result)
        except AgentError as exc:
            errors.append("%s: %s" % (sym, exc))
        except Exception as exc:
            log.exception("خطای غیرمنتظره در تحلیل %s", sym)
            errors.append("%s: خطای داخلی (%s)" % (sym, exc))

    return jsonify(ok=True, results=results,
                   errors=errors + isin_errors)


@app.get("/api/history")
def api_history():
    return jsonify(ok=True, data=db.history())


@app.get("/api/analysis/<int:item_id>")
def api_analysis(item_id):
    data = db.get_analysis(item_id)
    if not data:
        return jsonify(ok=False, error="یافت نشد."), 404
    return jsonify(ok=True, data=data)


@app.delete("/api/analysis/<int:item_id>")
def api_delete(item_id):
    db.delete_analysis(item_id)
    return jsonify(ok=True)


@app.get("/api/config")
def api_get_config():
    cfg = scoring.load_config()
    cfg["weights"] = scoring.normalize_weights(cfg["weights"])
    return jsonify(ok=True, config=cfg)


@app.post("/api/config")
def api_set_config():
    data = request.get_json(silent=True) or {}
    cfg = scoring.load_config()
    weights = data.get("weights")
    if isinstance(weights, dict):
        clean = {}
        for key in scoring.COMPONENT_LABELS:
            try:
                v = float(weights.get(key, cfg["weights"].get(key, 0)))
            except (TypeError, ValueError):
                v = cfg["weights"].get(key, 0)
            clean[key] = max(0.0, min(100.0, v)) / 100.0  # اسلایدر UI بر حسب درصد است
        cfg["weights"] = clean
    th = data.get("thresholds")
    if isinstance(th, dict):
        try:
            cfg["thresholds"] = {
                "buy": max(0, min(100, int(th.get("buy", cfg["thresholds"]["buy"])))),
                "hold": max(0, min(100, int(th.get("hold", cfg["thresholds"]["hold"])))),
                "watch": max(0, min(100, int(th.get("watch", cfg["thresholds"]["watch"])))),
            }
        except (TypeError, ValueError):
            pass
    risk = data.get("max_risk_per_trade_pct")
    if risk is not None:
        try:
            cfg["max_risk_per_trade_pct"] = max(0.5, min(50.0, float(risk)))
        except (TypeError, ValueError):
            pass
    scoring.save_config(cfg)
    cfg["weights"] = scoring.normalize_weights(cfg["weights"])
    return jsonify(ok=True, config=cfg)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
