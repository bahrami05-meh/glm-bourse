# -*- coding: utf-8 -*-
"""tactician.py — ایجنت ۳: استخراج نقاط تاکتیکی معامله.

بر مبنای خروجی ایجنت ۲ (اندیکاتورهای خام)، سطوح عملیاتی را محاسبه می‌کند:
- محدوده ورود (پول‌بک به EMA20 یا فیبوناچی 0.382-0.5)
- حد ضرر (زیر کیجون‌سن یا کف سوینگ اخیر منهای ۱×ATR — هرکدام نزدیک‌تر است تا
  حد ضرر منطقی و قابل‌اجرای بورس ایران باشد)
- هدف اول/دوم (سقف ۹۰ روزه و اکستنشن فیبوناچی)
- نسبت بازده به ریسک
- اندازه موقعیت بر اساس حداکثر ریسک هر معامله (از config)
"""
from .base import BaseAgent


class TacticianAgent(BaseAgent):
    name = "tactician"
    title = "ایجنت ۳ — نقاط تاکتیکی"

    def __init__(self, config):
        self.config = config

    def execute(self, context):
        raw = context["indicators_raw"]
        last = raw["last"]
        ema20 = raw["ema20"]
        kijun = raw["kijun"]
        atr_val = raw["atr"]
        fib = raw["fib"]
        swing_high = raw["swing_high"]
        swing_low = raw["swing_low"]
        scores = context.get("scores", {})

        # ----------------------------------------------------------- ورود
        # پول‌بک سالم: بین EMA20 و فیبو ۰٫۳۸۲؛ اگر قیمت اینجا بود، ورود پله‌ای
        fib382 = fib.get("0.382")
        fib50 = fib.get("0.5")
        if fib382:
            pullback_low = min(ema20, fib382)
            pullback_high = max(ema20, fib382)
        else:
            pullback_low, pullback_high = ema20, ema20 * 1.02
        # اگر قیمت زیر محدوده پول‌بک است، خود قیمت فعلی مرز پایین ورود است
        if last < pullback_low:
            pullback_low, pullback_high = last * 0.995, pullback_low
        # اگر قیمت خیلی بالاتر از محدوده پول‌بک است (بیش از ۳٪ فاصله)، انتظار
        # پول‌بک عمیق‌تر تا فیبو ۰٫۵ منطقی است؛ وگرنه ورود در اصلاح به EMA20
        if last > pullback_high * 1.03 and fib50 and fib50 > pullback_low:
            pullback_high = min(pullback_high, fib50) if fib50 > ema20 else max(ema20, fib50 * 0.99)
            pullback_low = min(ema20, fib50)
        entry_txt = "%s تا %s" % (self._fmt(pullback_low), self._fmt(pullback_high))

        # ------------------------------------------------------ حد ضرر
        # حد ضرر باید معنادار باشد: نه آن‌قدر نزدیک که با نوسان روزانه (ATR)
        # فعال شود، نه آن‌قدر دور که ریسک غیرقابل‌کنترل شود (حداکثر ۱۲٪).
        candidates = []
        if kijun:
            candidates.append(("زیر کیجون‌سن", kijun * 0.99))
        swing_stop = swing_low - atr_val
        candidates.append(("کف سوینگ منهای ATR", swing_stop))
        atr_floor = last - 3 * atr_val      # حداقل فاصله منطقی
        atr_ceiling = last * 0.88           # حداکثر فاصله ۱۲٪
        valid = [(l, v) for l, v in candidates
                 if atr_ceiling <= v < last and v >= atr_floor]
        if valid:
            # نزدیک‌ترین حد ضرر معتبر به قیمت (کمترین ریسک، قابل‌اجرای‌تر)
            best_v, stop_label = max((v, l) for l, v in valid)
            stop_price = best_v
        else:
            # هیچ کاندید در بازه معتبر نبود → حد ضرر مبتنی بر ATR
            stop_price = max(atr_floor, last - 2 * atr_val)
            stop_label = "۲ برابر ATR"
        stop_txt = "%s (%s، %.1f٪ پایین‌تر)" % (
            self._fmt(stop_price), stop_label, (last - stop_price) / last * 100)

        # --------------------------------------------------------- اهداف
        target1 = swing_high if swing_high > last * 1.02 else last * 1.05
        # هدف دوم: اگر سقف شکسته شود، اکستنشن = سقف + (سقف-کف)*0.272
        target2 = max(swing_high + (swing_high - swing_low) * 0.272, last * 1.08)
        targets_txt = [self._fmt(target1), self._fmt(target2)]

        # ------------------------------------------------- ریسک/بازده و اندازه
        risk_per_unit = last - stop_price
        reward1 = target1 - last
        rr = reward1 / risk_per_unit if risk_per_unit > 0 else None

        position_size_ratio = None
        risk_pct = self.config.get("max_risk_per_trade_pct", 5.0)
        if risk_per_unit > 0:
            # نسبت حجم موقعیت مجاز به کل سرمایه:
            # حداکثر ریسک مجاز = risk_pct٪ سرمایه؛ افت تا حد ضرر = drop_pct٪ قیمت
            # → درصد سرمایه قابل‌درگیر شدن = risk_pct / drop_pct
            # سقف ۵۰٪ سرمایه: پیشنهاد اندازه هرگز نباید بیش از نصف حساب باشد
            drop_pct = risk_per_unit / last * 100  # درصد افت تا حد ضرر
            position_size_ratio = min(risk_pct / drop_pct, 50.0) if drop_pct > 0 else None
            # اگر نسبت بازده/ریسک زیر ۲ است، ورود در قیمت فعلی منطقی نیست؛
            # اندازه پیشنهادی به‌صرفه صفر گزارش شود (باید در محدوده ورود شکار کرد)
            if rr is not None and rr < 2.0:
                position_size_ratio = 0.0

        rr_txt = ("%.2f" % rr) if rr is not None else "نامشخص"
        rr_ok = rr is not None and rr >= 2.0

        notes = []
        if rr_ok:
            notes.append("نسبت بازده/ریسک هدف اول ≥ ۲ — از نظر مدیریت ریسک قابل‌قبول")
        elif rr is not None:
            notes.append("نسبت بازده/ریسک هدف اول زیر ۲ — ورود فقط در قیمت بهتر منطقی است؛ "
                         "اندازه موقعیت صفر پیشنهاد شد تا در محدوده ورود (پول‌بک) شکار شود")
        pos_val = scores.get("price_position", {}).get("value")
        if pos_val is not None and pos_val > 0.85:
            notes.append("قیمت نزدیک سقف ۹۰ روزه است؛ ورود تهاجمی توصیه نمی‌شود")
        if scores.get("rsi", {}).get("value") is not None and scores["rsi"]["value"] > 70:
            notes.append("RSI در اشباع خرید؛ منتظر اصلاح برای ورود باشید")

        result = {
            "summary": "نقاط تاکتیکی بر مبنای فیبوناچی/ATR/کیجون‌سن محاسبه شد",
            "entry": entry_txt,
            "stop_loss": stop_txt,
            "targets": targets_txt,
            "risk_reward": rr_txt,
            "position_size_pct_of_capital": (round(position_size_ratio * 100, 1)
                                             if position_size_ratio is not None else None),
            "last_price": self._fmt(last),
            "notes": notes,
        }
        context["tactics"] = result
        return result

    @staticmethod
    def _fmt(v):
        try:
            return "{:,.0f}".format(float(v))
        except (TypeError, ValueError):
            return "—"
