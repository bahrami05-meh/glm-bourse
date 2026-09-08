# -*- coding: utf-8 -*-
"""base.py — کلاس پایه ایجنت‌ها.

هر ایجنت:
- نام و نقش فارسی دارد (برای نمایش در UI)
- متد run(context) دارد که context را ورودی می‌گیرد، نتیجه‌اش را در context
  می‌نویسد و خروجی ساختاریافته (dict) برمی‌گرداند
- خطاها را به شکل AgentError گزارش می‌کند تا زنجیره ایجنت‌ها با پیام گویا
  متوقف شود، نه کرش خام
"""
import logging
import time


log = logging.getLogger("glm.agents")


class AgentError(Exception):
    """خطای قابل‌نمایش به کاربر هنگام شکست یک ایجنت."""


class BaseAgent:
    name = "base"
    title = "ایجنت پایه"

    def run(self, context):
        t0 = time.time()
        try:
            result = self.execute(context)
        except AgentError:
            raise
        except Exception as exc:  # خطاهای غیرمنتظره هم به خطای گویا تبدیل شوند
            log.exception("خطا در ایجنت %s", self.name)
            raise AgentError("ایجنت «%s» با خطا متوقف شد: %s" % (self.title, exc))
        elapsed = round(time.time() - t0, 2)
        result["agent"] = self.name
        result["title"] = self.title
        result["elapsed_sec"] = elapsed
        context.setdefault("agent_outputs", {})[self.name] = result
        log.info("ایجنت %s در %.2f ثانیه تمام شد", self.name, elapsed)
        return result

    def execute(self, context):
        raise NotImplementedError
