# -*- coding: utf-8 -*-
"""processor.py — ایجنت ۲: پردازش اطلاعات و امتیازدهی وزنی.

هر پارامتر تکنیکال یک امتیاز ۰-۱۰۰ می‌گیرد:
  trend_ema       روند بر اساس EMA20/50/200 و جای قیمت
  ichimoku        قیمت نسبت به ابر و کیجون‌سن
  rsi             ناحیه RSI (۵۰ ایده‌آل؛ >۷۰ اشباع خرید؛ <۳۰ اشباع فروش)
  macd            جهت هیستوگرام و تقاطع
  volume          حجم امروز نسبت به میانگین ۳۰ روزه
  money_flow      جریان پول حقیقی (میانگین چند روز اخیر)
  price_position  جای قیمت در بازه سقف/کف ۹۰ روزه (نزدیکی به سقف = ریسک اصلاح)

خروجی در context["scores"]: dict نام مؤلفه → {score, value, reason}
"""
import pandas as pd

from .base import BaseAgent
from indicators import rsi, macd, atr, ichimoku, fibonacci_levels, _ema


def _clamp(v, lo=0.0, hi=100.0):
    return float(max(lo, min(hi, v)))


class ProcessorAgent(BaseAgent):
    name = "processor"
    title = "ایجنت ۲ — پردازش اطلاعات"

    MONEY_FLOW_DAYS = 5

    def execute(self, context):
        df = context["ohlcv"]
        ct = context.get("client_type")
        close = df["Close"]
        last = float(close.iloc[-1])
        scores = {}

        # ---------------------------------------------------------- روند EMA
        ema20, ema50 = _ema(close, 20), _ema(close, 50)
        ema200 = _ema(close, 200) if len(df) >= 200 else None
        reasons = []
        if last > ema20.iloc[-1] > ema50.iloc[-1]:
            s = 90.0
            reasons.append("قیمت بالای EMA20 و EMA20 بالای EMA50 (روند صعودی)")
        elif last < ema20.iloc[-1] < ema50.iloc[-1]:
            s = 10.0
            reasons.append("قیمت زیر EMA20 و EMA20 زیر EMA50 (روند نزولی)")
        else:
            s = 50.0
            reasons.append("میانگین‌ها درهم‌تنیده (روند نامشخص/رنج)")
        if ema200 is not None:
            if last > ema200.iloc[-1]:
                s = min(100.0, s + 10.0)
                reasons.append("بالای EMA200")
            else:
                s = max(0.0, s - 10.0)
                reasons.append("زیر EMA200")
        scores["trend_ema"] = {"score": _clamp(s), "value": round(float(ema20.iloc[-1]), 1),
                               "reason": "؛ ".join(reasons)}

        # ---------------------------------------------------------- ایچیموکو
        tenkan, kijun, senkou_a, senkou_b = ichimoku(df)
        s, why = 50.0, "داده ایچیموکو ناکافی"
        sa = senkou_a.iloc[-1]
        sb = senkou_b.iloc[-1]
        if pd.notna(sa) and pd.notna(sb):
            top = max(sa, sb)
            bottom = min(sa, sb)
            if last > top:
                s = 90.0
                why = "قیمت بالای ابر (روند صعودی تأییدشده)"
            elif last < bottom:
                s = 10.0
                why = "قیمت زیر ابر (روند نزولی تأییدشده)"
            else:
                s = 45.0
                why = "قیمت داخل ابر (بی‌طرف)"
            kj = kijun.iloc[-1]
            if pd.notna(kj) and kj:
                dist = (last - kj) / kj * 100
                if dist > 15:
                    s = _clamp(s - 20)
                    why += "؛ فاصله %.1f٪ از کیجون‌سن (ریسک بازگشت)" % dist
                elif dist < -15:
                    s = _clamp(s + 20)
                    why += "؛ %.1f٪ زیر کیجون‌سن (احتمال بازگشت صعودی)" % abs(dist)
        kijun_val = float(kijun.iloc[-1]) if pd.notna(kijun.iloc[-1]) else None
        scores["ichimoku"] = {"score": s, "value": kijun_val, "reason": why}

        # ---------------------------------------------------------------- RSI
        r = rsi(close).iloc[-1]
        # ناحیه ۴۵-۶۰ بهترین؛ از آن دورتر (چه بالا چه پایین) امتیاز کم می‌شود،
        # ولی اشباع خرید جریمه سنگین‌تر دارد (ریسک ورود در سقف)
        if r > 70:
            s = _clamp(100 - (r - 70) * 3.3)
            why = "اشباع خرید (%.1f) — ریسک اصلاح" % r
        elif r < 30:
            s = _clamp(30 + (30 - r) * 1.2)
            why = "اشباع فروش (%.1f) — احتمال برگشت، اما هنوز سیگنال تأیید نیست" % r
        else:
            s = _clamp(100 - abs(r - 50) * 2)
            why = "ناحیه سالم (%.1f)" % r
        scores["rsi"] = {"score": s, "value": round(float(r), 1), "reason": why}

        # --------------------------------------------------------------- MACD
        m_line, m_signal, m_hist = macd(close)
        hist_now = float(m_hist.iloc[-1])
        hist_prev = float(m_hist.iloc[-2]) if len(m_hist) > 1 else 0.0
        s = 50.0
        if hist_now > 0:
            s += 25
        else:
            s -= 25
        if hist_now > hist_prev:
            s += 20  # هیستوگرام در حال تقویت
            why = "هیستوگرام مثبت و رو به تقویت" if hist_now > 0 else "هیستوگرام منفی ولی در حال بهبود"
        else:
            s -= 20
            why = "هیستوگرام مثبت ولی رو به تضعیف" if hist_now > 0 else "هیستوگرام منفی و در حال تضعیف"
        # تقاطع اخیر (۳ کندل اخیر علامت عوض کرده) اثر جهت‌دار
        if len(m_hist) > 3:
            crossed = (hist_now > 0) != (float(m_hist.iloc[-3]) > 0)
            if crossed:
                s = _clamp(s + (10 if hist_now > 0 else -10))
                why += "؛ تقاطع اخیر"
        scores["macd"] = {"score": _clamp(s), "value": round(hist_now, 2), "reason": why}

        # ------------------------------------------------------- حجم و نقدشوندگی
        vol = df["Volume"]
        avg30 = vol.tail(30).mean()
        vol_ratio = float(vol.iloc[-1] / avg30) if avg30 > 0 else 1.0
        # حجم بیش از حد بالاتر از میانگین همراه با قیمت بالا = خروج احتمالی پول؛
        # ۰٫۵ تا ۲ برابر میانگین محدوده سالم است
        if vol_ratio < 0.5:
            s, why = 35.0, "حجم بسیار کمتر از میانگین (%.1f×) — بی‌رمقی بازار" % vol_ratio
        elif vol_ratio <= 2.0:
            s, why = _clamp(60 + vol_ratio * 20), "حجم سالم (%.1f× میانگین ۳۰ روزه)" % vol_ratio
        else:
            s, why = 55.0, "حجم غیرعادی بالا (%.1f×) — احتمال توزیع/فشار فروش" % vol_ratio
        scores["volume"] = {"score": s, "value": round(vol_ratio, 2), "reason": why}

        # -------------------------------------------------------- حقیقی/حقوقی
        if ct is not None and len(ct):
            recent = ct.tail(self.MONEY_FLOW_DAYS)
            flows = (recent["buy_I"] - recent["sell_I"])
            totals = (recent["buy_I"] + recent["sell_I"])
            # جریان خالص نرمال‌شده: نسبت خالص خرید حقیقی به کل معاملات حقیقی
            ratio = float(flows.sum() / totals.sum()) if totals.sum() > 0 else 0.0
            s = _clamp(50 + ratio * 250)  # ±20% خالص → ±50 امتیاز
            pos_days = int((flows > 0).sum())
            why = "میانگین %d روز: خالص %s (نسبت %+.1f٪، %d روز از %d روز ورود پول)" % (
                len(recent), "ورود پول حقیقی" if ratio > 0 else "خروج پول حقیقی",
                ratio * 100, pos_days, len(recent))
            scores["money_flow"] = {"score": s, "value": round(ratio, 3), "reason": why}
        else:
            scores["money_flow"] = {"score": None, "value": None,
                                    "reason": "داده حقیقی/حقوقی در دسترس نبود (وزن به بقیه منتقل شد)"}

        # ------------------------------------------------- موقعیت قیمت (فیبو/بازه)
        fib, swing_high, swing_low = fibonacci_levels(df, lookback=90)
        rng = swing_high - swing_low
        pos = (last - swing_low) / rng if rng > 0 else 0.5  # 0=کف، 1=سقف
        # نزدیکی کف ۹۰ روزه امتیاز بالا (فضای رشد)، نزدیکی سقف امتیاز پایین (ریسک اصلاح)
        s = _clamp(100 - pos * 70)  # pos=0 → 100, pos=1 → 30
        why = "قیمت در %.0f٪ بازه ۹۰ روزه (سقف %.0f / کف %.0f)" % (pos * 100, swing_high, swing_low)
        scores["price_position"] = {"score": s, "value": round(pos, 2), "reason": why}

        context["scores"] = scores
        # اندیکاتورهای خام برای ایجنت ۳ (نقاط تاکتیکی)
        context["indicators_raw"] = {
            "last": last,
            "ema20": float(ema20.iloc[-1]),
            "ema50": float(ema50.iloc[-1]),
            "kijun": kijun_val,
            "tenkan": float(tenkan.iloc[-1]) if pd.notna(tenkan.iloc[-1]) else None,
            "atr": float(atr(df).iloc[-1]),
            "fib": fib,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "avg30_volume": float(avg30),
        }
        return {
            "summary": "امتیازدهی ۷ مؤلفه تکنیکال انجام شد",
            "scores": {k: {"score": (round(v["score"], 1) if v["score"] is not None else None),
                           "value": v["value"], "reason": v["reason"]}
                       for k, v in scores.items()},
        }
