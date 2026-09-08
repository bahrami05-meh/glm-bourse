# -*- coding: utf-8 -*-
"""scoring.py — موتور امتیازدهی وزنی.

هر پارامتر تکنیکال یک امتیاز ۰ تا ۱۰۰ می‌گیرد و امتیاز کل = Σ(امتیاز × وزن).
وزن‌ها از config خوانده می‌شوند و مجموعشان باید ۱ باشد (اگر نبود، نرمال می‌شود).
"""
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# توضیح فارسی هر مؤلفه برای نمایش در UI
COMPONENT_LABELS = {
    "trend_ema": "روند (EMA20/EMA50/EMA200)",
    "ichimoku": "ایچیموکو (قیمت نسبت به ابر/کیجون)",
    "rsi": "RSI (اشباع خرید/فروش)",
    "macd": "MACD (تقاطع و هیستوگرام)",
    "volume": "حجم و نقدشوندگی",
    "money_flow": "حقیقی/حقوقی (جریان پول)",
    "price_position": "موقعیت قیمت (فیبوناچی/سقف-کف)",
}

DEFAULTS = {
    "weights": {
        "trend_ema": 0.20,
        "ichimoku": 0.15,
        "rsi": 0.15,
        "macd": 0.15,
        "volume": 0.10,
        "money_flow": 0.15,
        "price_position": 0.10,
    },
    "thresholds": {
        "buy": 70,
        "hold": 55,
        "watch": 40,
    },
    "max_risk_per_trade_pct": 5.0,
    "default_symbols": ["فولاد", "فملی", "شبندر"],
}


def load_config():
    cfg = {}
    cfg.update(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        for key in DEFAULTS:
            if isinstance(data.get(key), dict):
                cfg[key].update(data[key])
            elif key in data:
                cfg[key] = data[key]
    except FileNotFoundError:
        save_config(cfg)  # اولین اجرا: پیش‌فرض‌ها را روی دیسک بنویس
    except (OSError, ValueError):
        pass  # config خراب → پیش‌فرض
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)


def normalize_weights(weights):
    """مجموع وزن‌ها را به ۱ می‌رساند تا امتیاز نهایی همیشه در بازه ۰-۱۰۰ بماند."""
    total = float(sum(weights.values()))
    if total <= 0:
        # همه صفر → پیش‌فرض
        return dict(DEFAULTS["weights"])
    return {k: v / total for k, v in weights.items()}


def weighted_total(component_scores, weights):
    """component_scores: dict نام مؤلفه → امتیاز ۰-۱۰۰. خروجی: امتیاز کل ۰-۱۰۰.

    اگر بعضی مؤلفه‌ها در دسترس نبودند، وزن‌شان بین بقیه بازتوزیع می‌شود تا امتیاز
    نهایی همچنان در بازه ۰-۱۰۰ معنادار بماند.
    """
    w = normalize_weights(weights)
    total = 0.0
    used = 0.0
    for name, score in component_scores.items():
        if name in w and score is not None:
            total += float(score) * w[name]
            used += w[name]
    if used <= 0:
        return 0.0
    if used < 1.0 - 1e-9:
        # بازتوزیع: بخشی از وزن مؤلفه‌های غایب به موجودها منتقل می‌شود
        total = total / used
    return round(max(0.0, min(100.0, total)), 1)
