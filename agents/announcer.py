# -*- coding: utf-8 -*-
"""announcer.py — ایجنت ۴: اعلام نتیجه نهایی.

امتیاز وزنی کل (از scoring.weighted_total) را به سیگنال استاندارد تبدیل می‌کند:
  امتیاز ≥ buy آستانه  → «خرید»
  ≥ hold آستانه        → «نگهداری»
  ≥ watch آستانه       → «نظاره»
  < watch              → «فروش»
و دلایل مثبت/منفی را از امتیاز مؤلفه‌ها استخراج می‌کند.
"""
from .base import BaseAgent
import scoring


class AnnouncerAgent(BaseAgent):
    name = "announcer"
    title = "ایجنت ۴ — اعلام نتیجه"

    def __init__(self, config):
        self.config = config

    def execute(self, context):
        scores = context.get("scores", {})
        weights = self.config.get("weights", scoring.DEFAULTS["weights"])
        th = self.config.get("thresholds", scoring.DEFAULTS["thresholds"])

        component_scores = {k: v.get("score") for k, v in scores.items()}
        total = scoring.weighted_total(component_scores, weights)

        if total >= th.get("buy", 70):
            signal = "خرید"
        elif total >= th.get("hold", 55):
            signal = "نگهداری"
        elif total >= th.get("watch", 40):
            signal = "نظاره"
        else:
            signal = "فروش"

        # دلایل: قوی‌ترین مؤلفه‌های مثبت و منفی
        labeled = []
        for key, data in scores.items():
            label = scoring.COMPONENT_LABELS.get(key, key)
            score = data.get("score")
            if score is None:
                labeled.append((None, label, data.get("reason", "")))
            else:
                labeled.append((float(score), label, data.get("reason", "")))

        positives = sorted([x for x in labeled if x[0] is not None and x[0] >= 65],
                           key=lambda x: -x[0])[:3]
        negatives = sorted([x for x in labeled if x[0] is not None and x[0] < 45],
                           key=lambda x: x[0])[:3]
        missing = [x for x in labeled if x[0] is None]

        reasons = ["%s: %s" % (label, reason) for _, label, reason in positives]
        risks = ["%s: %s" % (label, reason) for _, label, reason in negatives]
        risks += ["%s: %s" % (label, reason) for _, label, reason in missing]

        tactics = context.get("tactics", {})
        summary = (
            "امتیاز کل %s از ۱۰۰ → سیگنال «%s». ورود در محدوده %s، حد ضرر %s، "
            "هدف‌ها %s. نسبت بازده/ریسک: %s." % (
                total, signal, tactics.get("entry", "—"), tactics.get("stop_loss", "—"),
                " و ".join(tactics.get("targets", ["—"])), tactics.get("risk_reward", "—"))
        )

        result = {
            "summary": summary,
            "total_score": total,
            "signal": signal,
            "thresholds": th,
            "reasons": reasons or ["هیچ مؤلفه‌ای امتیاز قوی نداشت"],
            "risks": risks or ["ریسک مشخصی یافت نشد"],
            "disclaimer": "این خروجی فقط برای تحلیل و آموزش است؛ سیگنال خرید/فروش نیست و تأیید نهایی با شماست.",
        }
        context["final"] = result
        return result
