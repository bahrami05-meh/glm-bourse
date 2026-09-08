# -*- coding: utf-8 -*-
"""tsetmc_client.py — دریافت دیتای زنده از TSETMC (سایت رسمی بورس تهران).

اپ دیگر نیازی به آپلود دستی فایل اکسل ندارد؛ این ماژول همان درخواست‌های JSON ای را که
فرانت‌اند جدید سایت TSETMC می‌زند، مستقیم (یا از طریق پروکسی محلی کاربر) اجرا می‌کند.

توجه (مهم): سایت TSETMC به‌طور کامل به SPA جدید منتقل شده و endpointهای قدیمی
(Loader.aspx، aspx/symbol/FindSymbol.aspx) دیگر خروجی JSON نمی‌دهند. endpointهای
فعلی که تست شده و کار می‌کنند:
  - /api/Instrument/GetInstrumentSearch/{نام‌نماد}     → جستجوی نماد
  - /api/ClosingPrice/GetClosingPriceDailyList/{insCode}/0 → کل سابقه روزانه
    (جدید→قدیم؛ dEven=تاریخ میلادی YYYYMMDD، priceFirst/Open، priceMax/High،
     priceMin/Low، pClosing/Close پایانی، qTotTran5J/حجم)
  - /api/ClientType/GetClientTypeHistory/{insCode}     → کل سابقه حقیقی/حقوقی
  - /api/ClientType/GetClientType/{insCode}/0/1        → فقط آخرین روز (زنده)

پروکسی: درخواست‌ها اول مستقیم امتحان می‌شوند؛ اگر متغیر محیطی TSE_PROXY ست شده باشد
(مثلاً socks5h://127.0.0.1:2080) در صورت شکست مسیر مستقیم، از پروکسی هم تلاش می‌شود.
TSE_PROXY=none فقط مستقیم، TSE_PROXY=only فقط پروکسی. در نهایت خطای قابل‌فهم داده
می‌شود تا caller بتواند به مسیر آپلود فایل دستی برگردد (fallback).

نیازمندی اضافه برای پروکسی SOCKS: pip install pysocks
"""
import logging
import os
import time

import pandas as pd
import requests


class MarketDataError(Exception):
    """خطای قابل‌نمایش به کاربر هنگام ناموفق بودن دریافت داده‌ی بازار."""


def _standardize_columns(df):
    """استانداردسازی ستون‌های OHLCV (کپی محلی از market_data پروژه مرجع تا این
    پروژه مستقل بماند)."""
    df = df.copy()
    df.columns = [str(c).strip().title() for c in df.columns]
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)
    if missing:
        raise MarketDataError(
            "ستون‌های مورد نیاز در داده‌ی دریافتی از TSETMC نبود: " + "، ".join(sorted(missing))
        )
    for col in ("Open", "High", "Low", "Close", "Volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["Open", "High", "Low", "Close"])

log = logging.getLogger("brs.tsetmc")

BASE = "https://cdn.tsetmc.com"
TIMEOUT = 20
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.tsetmc.com/",
}


def _proxies_list():
    """ترتیب تلاش: اول مستقیم (چون در تست عملی، اتصال مستقیم به TSETMC از شبکه‌های
    داخلی ایران معمولاً سریع‌تر و پایدارتر است)، بعد پروکسی اگر ست باشد.

    نکته: ویندوز اغلب یک پروکسی سیستم (ابزار فیلترشکن، ProxyServer در تنظیمات اینترنت)
    دارد که requests به‌طور پیش‌فرض از آن پیروی می‌کند (trust_env)؛ برای TSETMC این
    مسیر کند/ناپایدار است، پس sess.trust_env را خاموش می‌کنیم و صریحاً پروکسی
    انتخابی خودمان را فقط در صورت تنظیم TSE_PROXY استفاده می‌کنیم.

    TSE_PROXY=none → فقط مستقیم. TSE_PROXY=only → فقط پروکسی.
    """
    out = [None]  # اتصال مستقیم
    proxy = (os.environ.get("TSE_PROXY") or "").strip()
    if proxy and proxy.lower() == "only":
        return [{"http": proxy, "https": proxy}]
    if proxy and proxy.lower() != "none":
        out.append({"http": proxy, "https": proxy})
    return out


_session = requests.Session()
_session.trust_env = False  # پروکسی سیستم‌عامل را نادیده بگیر (بالا را ببین)


def _get(url):
    """GET با retry کوتاه روی چند مسیر (پروکسی/مستقیم). خروجی: dict (JSON)."""
    last_err = None
    for proxies in _proxies_list():
        for attempt in (1, 2):
            try:
                r = _session.get(url, headers=HEADERS, timeout=TIMEOUT, proxies=proxies)
                if r.status_code != 200:
                    raise requests.HTTPError("HTTP %s" % r.status_code)
                return r.json()
            except Exception as exc:
                last_err = exc
                log.debug("GET %s تلاش %d (proxies=%s) شکست خورد: %s",
                          url, attempt, bool(proxies), exc)
                time.sleep(0.8)
    raise MarketDataError(
        "دسترسی به TSETMC ناموفق بود (%s). اگر VPN/پروکسی داری روشنش کن "
        "(یا TSE_PROXY را در .env تنظیم کن) و دوباره امتحان کن." % last_err
    )


# ------------------------------------------------------------------ جستجوی نماد
def find_symbol(symbol):
    """نام فارسی نماد را به (insCode, name) تبدیل می‌کند.

    اگر چند نتیجه بود، دقیق‌ترین تطابق (lVal18AFC == نام خواسته‌شده یا شروع‌شدن
    نام رسمی با آن) انتخاب می‌شود؛ چون GetInstrumentSearch زیررشته‌ای جستجو می‌کند
    و گزینه‌های مشابه (اختیار معامله و…) هم برمی‌گرداند. اگر هیچ تطابقی نبود خطای
    گویا می‌دهیم — تحلیل اشتباه نماد، بدتر از نداشتن دیتاست.
    """
    symbol = (symbol or "").strip()
    if not symbol:
        raise MarketDataError("نام نماد خالی است.")
    data = _get(BASE + "/api/Instrument/GetInstrumentSearch/" + requests.utils.quote(symbol))
    rows = data.get("instrumentSearch") or []
    rows = [r for r in rows if isinstance(r, dict) and r.get("insCode")]
    if not rows:
        raise MarketDataError(
            "نماد «%s» در TSETMC پیدا نشد. نام باید دقیقاً مطابق سایت باشد "
            "(مثلاً «شبندر»، نه «شبندر سهام»)." % symbol
        )

    def score(r):
        tiker = str(r.get("lVal18AFC") or "").strip()
        name = str(r.get("lVal30") or "").strip()
        if tiker == symbol:
            return 0
        if tiker.startswith(symbol) or name.startswith(symbol):
            return 1
        return 2

    rows.sort(key=score)
    best = rows[0]
    return str(best["insCode"]), str(best.get("lVal18AFC") or symbol)


# --------------------------------------------------------------- سابقه قیمت
def fetch_ohlcv(symbol, limit=300):
    """دیتای OHLCV روزانه نماد را مستقیم از TSETMC می‌خواند.

    خروجی: DataFrame ستون‌های Open/High/Low/Close/Volume (سازگار با indicators.py)

    نکته فرمت: pClosing در TSETMC «قیمت پایانی» است (میانگین وزنی معاملات روز، همان
    مبنای قیمت مجاز فردا) و priceLast «آخرین معامله». چون سابقه رسمی خروجی اکسل خود
    سایت (که تحلیل‌های قبلی روی آن بنا شده) مبتنی بر قیمت پایانی است، از pClosing
    به‌عنوان Close استفاده می‌کنیم.
    """
    ins_code, name = find_symbol(symbol)
    data = _get(BASE + "/api/ClosingPrice/GetClosingPriceDailyList/" + ins_code + "/0")
    rows = data.get("closingPriceDaily") or []
    # پاسخ جدید→قدیم است؛ برای DataFrame به ترتیب قدیم→جدید نیاز داریم
    parsed = []
    for row in rows:
        try:
            parsed.append({
                "_date": str(int(row["dEven"])),
                "Open": float(row["priceFirst"]),
                "High": float(row["priceMax"]),
                "Low": float(row["priceMin"]),
                "Close": float(row["pClosing"]),
                "Volume": float(row["qTotTran5J"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    parsed.reverse()

    df = pd.DataFrame(parsed)
    df["_date"] = pd.to_datetime(df["_date"], format="%Y%m%d", errors="coerce")
    df = df[df["_date"].notna()].sort_values("_date")
    # روزهای توقف/بدون معامله که High/Low/Open صفر دارند کندل معتبر نیستند
    df = df[(df["High"] > 0) & (df["Low"] > 0) & (df["Open"] > 0)]
    df = df.drop(columns="_date").tail(limit).reset_index(drop=True)

    if len(df) < 30:
        raise MarketDataError(
            "دیتای کافی برای نماد «%s» از TSETMC گرفته نشد (فقط %d کندل معتبر)."
            % (name, len(df))
        )

    df = _standardize_columns(df)
    log.info("دیتای زنده‌ی %s از TSETMC دریافت شد: %d کندل", name, len(df))
    return df


def fetch_closing_daily(ins_code):
    """سابقه روزانه خام (شامل dEven و قیمت‌ها) را برای meta برمی‌گرداند.

    فرقش با fetch_ohlcv این است که ستون dEven (تاریخ میلادی) را نگه می‌دارد تا
    تازگی داده قابل‌بررسی باشد.
    """
    try:
        data = _get(BASE + "/api/ClosingPrice/GetClosingPriceDailyList/" + ins_code + "/0")
    except MarketDataError:
        return None
    rows = data.get("closingPriceDaily") or []
    if not rows:
        return None
    return pd.DataFrame(rows)


# --------------------------------------------------------------- تابلوخوانی
def fetch_client_type_history(symbol):
    """کل سابقه حقیقی/حقوقی نماد را از TSETMC می‌خواند.

    خروجی: DataFrame با ستون‌های date, buy_I, sell_I, buy_N, sell_N
    (حجم خرید/فروش حقیقی و حقوقی) یا None اگر در دسترس نبود.
    """
    try:
        ins_code, _ = find_symbol(symbol)
        data = _get(BASE + "/api/ClientType/GetClientTypeHistory/" + ins_code)
        rows = data.get("clientType") or []
        if not isinstance(rows, list) or not rows:
            return None
        out = []
        for row in rows:
            try:
                out.append({
                    "date": int(row["recDate"]),
                    "buy_I": float(row["buy_I_Volume"]),
                    "sell_I": float(row["sell_I_Volume"]),
                    "buy_N": float(row["buy_N_Volume"]),
                    "sell_N": float(row["sell_N_Volume"]),
                })
            except (KeyError, TypeError, ValueError):
                continue
        if not out:
            return None
        df = pd.DataFrame(out).dropna().sort_values("date")
        return df
    except MarketDataError as exc:
        log.warning("دریافت حقیقی/حقوقی ناموفق بود: %s", exc)
        return None


def fetch_client_type_summary(symbol, days=5):
    """خلاصه‌ی حقیقی/حقوقی برای تابلوخوانی (ورود/خروج پول حقیقی، قدرت خریدار).

    خروجی: متن فارسی کوتاه برای افزودن به پرامپت مدل، یا None اگر در دسترس نبود.
    """
    df = fetch_client_type_history(symbol)
    if df is None or df.empty:
        return None
    df = df.tail(days)
    lines = []
    for _, row in df.iterrows():
        if row["buy_I"] + row["sell_I"] == 0:
            continue
        money_flow = row["buy_I"] - row["sell_I"]
        power = row["buy_I"] / row["sell_I"] if row["sell_I"] else float("inf")
        lines.append(
            "روز %d: خرید حقیقی=%.0f، فروش حقیقی=%.0f → %s (نسبت %.2f)" % (
                row["date"], row["buy_I"], row["sell_I"],
                "ورود پول حقیقی" if money_flow > 0 else "خروج پول حقیقی",
                power if power != float("inf") else 999,
            )
        )
    if not lines:
        return None
    return "داده‌ی حقیقی/حقوقی تابلو (از TSETMC):\n" + "\n".join(lines)
