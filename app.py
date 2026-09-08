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

from flask import Flask, jsonify, render_template, request

import scoring
import db
from agents.base import AgentError
from agents.collector import CollectorAgent
from agents.processor import ProcessorAgent
from agents.tactician import TacticianAgent
from agents.announcer import AnnouncerAgent

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
                           risk_pct=cfg.get("max_risk_per_trade_pct", 5))


@app.post("/api/analyze")
def api_analyze():
    data = request.get_json(silent=True) or {}
    symbols_raw = (data.get("symbols") or "").strip()
    if not symbols_raw:
        return jsonify(ok=False, error="حداقل یک نماد وارد کنید."), 400
    import re as _re
    symbols = [s.strip() for s in _re.split(r"[,،\n]+", symbols_raw) if s.strip()][:20]
    if not symbols:
        return jsonify(ok=False, error="نام نماد معتبر نیست."), 400

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

    return jsonify(ok=True, results=results, errors=errors)


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
