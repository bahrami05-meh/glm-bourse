# -*- coding: utf-8 -*-
"""collector.py — ایجنت ۱: جمع‌آوری اطلاعات بازار از TSETMC.

وظیفه: برای هر نماد، سابقه قیمت روزانه و سابقه حقیقی/حقوقی را از TSETMC می‌گیرد،
تازگی داده و وضعیت معامله نماد را اعتبارسنجی می‌کند و نتیجه را در context می‌گذارد.

خروجی (in context):
  context["ohlcv"]  — دیتافریم OHLCV
  context["client_type"] — دیتافریم حقیقی/حقوقی یا None
  context["market_meta"] — نام نماد، آخرین تاریخ داده، تازگی، قیمت آخر
"""
import datetime as dt

import pandas as pd

from .base import BaseAgent, AgentError
from agents import tsetmc_client
from agents.tsetmc_client import MarketDataError# حداکثر فاصله مجاز تاریخ آخرین کندل تا امروز (روز تقویمی). تعطیلات طولانی
# (نوروز و...) ممکن است حتی با بازار سالم این فاصله را بزرگ کند؛ پس فقط «هشدار»
# می‌دهیم نه توقف، مگر خیلی قدیمی‌تر از آن.
STALE_WARN_DAYS = 6
STALE_BLOCK_DAYS = 21


class CollectorAgent(BaseAgent):
    name = "collector"
    title = "ایجنت ۱ — جمع‌آوری اطلاعات"

    def __init__(self, limit=300):
        self.limit = limit

    def execute(self, context):
        symbol = context.get("symbol", "").strip()
        if not symbol:
            raise AgentError("نام نماد خالی است.")

        try:
            ohlcv = tsetmc_client.fetch_ohlcv(symbol, limit=self.limit)
        except MarketDataError as exc:
            raise AgentError(str(exc))

        meta = {
            "ins_code": ohlcv.attrs.get("ins_code"),
            "last_date": None,
            "last_close": float(ohlcv["Close"].iloc[-1]),
            "stale_days": None,
            "stale_level": "ok",
        }
        try:
            client_type = tsetmc_client.fetch_client_type_history(symbol)
        except Exception:
            client_type = None

        # تازگی داده: آخرین کندل باید نسبتاً نزدیک امروز باشد
        ins_code, name = tsetmc_client.find_symbol(symbol)
        meta["ins_code"] = ins_code
        meta["name"] = name
        daily = tsetmc_client.fetch_closing_daily(ins_code)
        if daily is not None and len(daily):
            last_date = pd.to_datetime(str(daily.iloc[0]["dEven"]), format="%Y%m%d")
            meta["last_date"] = str(last_date.date())
            meta["stale_days"] = (dt.date.today() - last_date.date()).days
            if meta["stale_days"] >= STALE_BLOCK_DAYS:
                meta["stale_level"] = "blocked"
            elif meta["stale_days"] >= STALE_WARN_DAYS:
                meta["stale_level"] = "warn"
            # وضعیت جریان پول حقیقی آخرین روز
            if client_type is not None and len(client_type):
                last_ct = client_type.iloc[-1]
                meta["last_money_flow"] = float(last_ct["buy_I"] - last_ct["sell_I"])

        if meta["stale_level"] == "blocked":
            raise AgentError(
                "داده‌ی %s قدیمی است (آخرین کندل: %s؛ %d روز قبل). احتمالاً نماد متوقف است؛ "
                "تحلیل با داده کهنه مجاز نیست." % (name, meta["last_date"], meta["stale_days"])
            )

        context["ohlcv"] = ohlcv
        context["client_type"] = client_type
        context["market_meta"] = meta
        return {
            "summary": "دریافت %d کندل از TSETMC برای «%s» (آخرین داده: %s)" % (
                len(ohlcv), name, meta.get("last_date") or "نامشخص"),
            "candles": len(ohlcv),
            "meta": meta,
            "warnings": (["داده %d روز قدیمی‌تر از امروز است؛ در تفسیر لحاظ شود."
                          % meta["stale_days"]] if meta["stale_level"] == "warn" else []),
        }
