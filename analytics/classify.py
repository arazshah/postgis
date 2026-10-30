"""تشخیص منبع ورود از UTM، شناسه کلیک، Referer و User-Agent. بدون وابستگی خارجی."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

CLICK_IDS = {"gclid": ("google", "cpc"), "fbclid": ("facebook", "social"), "li_fat_id": ("linkedin", "paid"),
             "msclkid": ("bing", "cpc"), "yclid": ("yandex", "cpc"), "ttclid": ("tiktok", "paid")}

# پایان دامنه ← (منبع، نوع)
REFERRERS = [
    ("google.", "google", "organic"), ("bing.com", "bing", "organic"), ("yandex.", "yandex", "organic"),
    ("duckduckgo.com", "duckduckgo", "organic"), ("search.yahoo.com", "yahoo", "organic"),
    ("lnkd.in", "linkedin", "social"), ("linkedin.com", "linkedin", "social"),
    ("t.me", "telegram", "social"), ("telegram.org", "telegram", "social"), ("telegram.me", "telegram", "social"),
    ("instagram.com", "instagram", "social"), ("facebook.com", "facebook", "social"),
    ("fb.com", "facebook", "social"), ("twitter.com", "twitter", "social"), ("t.co", "twitter", "social"),
    ("x.com", "twitter", "social"), ("whatsapp.com", "whatsapp", "social"), ("wa.me", "whatsapp", "social"),
    ("eitaa.com", "eitaa", "social"), ("bale.ai", "bale", "social"), ("ble.ir", "bale", "social"),
    ("rubika.ir", "rubika", "social"), ("aparat.com", "aparat", "video"), ("youtube.com", "youtube", "video"),
    ("youtu.be", "youtube", "video"), ("github.com", "github", "referral"),
    ("reddit.com", "reddit", "social"), ("aut.ac.ir", "aut.ac.ir", "referral"),
    # اندروید به‌جای دامنه، نام بسته‌ی برنامه را به‌عنوان Referer می‌فرستد (android-app://com.linkedin.android)
    ("com.linkedin.android", "linkedin", "social"), ("com.instagram.android", "instagram", "social"),
    ("org.telegram.messenger", "telegram", "social"), ("org.telegram.messenger.web", "telegram", "social"),
    ("com.facebook.katana", "facebook", "social"), ("com.twitter.android", "twitter", "social"),
    ("com.whatsapp", "whatsapp", "social"), ("ir.eitaa.messenger", "eitaa", "social"),
    ("ir.nasim", "bale", "social"), ("ir.resaneh1.iptv", "rubika", "social"),
    ("com.google.android.googlequicksearchbox", "google", "organic"),
]

BOT_RE = re.compile(
    r"bot\b|bot/|crawl|spider|slurp|facebookexternalhit|preview|headless|python-requests|python-urllib|curl/|wget|"
    r"monitor|uptime|lighthouse|ahrefs|semrush|mj12|dotbot|petalbot|bytespider|go-http-client|okhttp|httpclient|"
    r"scrapy|java/|libwww|axios|node-fetch|whatsapp/|skypeuripreview|embedly|quora link|pinterest|vkshare", re.I)

IN_APP = [("instagram", re.compile(r"Instagram", re.I)), ("facebook", re.compile(r"FBAN|FBAV|FB_IAB", re.I)),
          ("linkedin", re.compile(r"LinkedInApp", re.I)), ("twitter", re.compile(r"Twitter", re.I)),
          ("telegram", re.compile(r"Telegram", re.I)), ("bale", re.compile(r"\bBale\b|Bale/", re.I)),
          ("eitaa", re.compile(r"Eitaa", re.I)), ("rubika", re.compile(r"Rubika", re.I)),
          ("line", re.compile(r"\bLine/", re.I))]

_CLEAN = re.compile(r"[^a-z0-9._\-؀-ۿ ]+")


def clean(value: str | None, limit: int) -> str:
    """نام‌ها یکدست و کوتاه شوند تا «LinkedIn» و «linkedin» دو منبع جدا نشوند."""
    return _CLEAN.sub("", (value or "").strip().lower())[:limit].strip()


def is_bot(ua: str) -> bool:
    return not ua or bool(BOT_RE.search(ua))


def device_info(ua: str) -> tuple[str, str, str]:
    """(دستگاه، مرورگر، مرورگر داخلی برنامه)"""
    low = ua.lower()
    if "ipad" in low or ("android" in low and "mobile" not in low) or "tablet" in low:
        device = "tablet"
    elif "mobi" in low or "iphone" in low or "android" in low:
        device = "mobile"
    else:
        device = "desktop"
    if "edg/" in low or "edga/" in low or "edgios/" in low:
        browser = "edge"
    elif "opr/" in low or "opera" in low:
        browser = "opera"
    elif "samsungbrowser" in low:
        browser = "samsung"
    elif "firefox" in low or "fxios" in low:
        browser = "firefox"
    elif "chrome" in low or "crios" in low:
        browser = "chrome"
    elif "safari" in low:
        browser = "safari"
    else:
        browser = "other"
    in_app = next((name for name, rx in IN_APP if rx.search(ua)), "")
    return device, browser, in_app


def referrer_host(referer: str, own_hosts: set[str]) -> str:
    """دامنه Referer؛ اگر از خود سایت باشد خالی برمی‌گردد."""
    try:
        host = (urlsplit(referer).hostname or "").lower()
    except ValueError:
        return ""
    host = host.removeprefix("www.")
    if not host or host in own_hosts or any(host.endswith("." + h) for h in own_hosts):
        return ""
    return host[:120]


def _host_matches(host: str, pattern: str) -> bool:
    if pattern.endswith("."):  # مثل google. ← google.com و google.co.uk
        return ("." + pattern) in ("." + host + ".")
    return host == pattern or host.endswith("." + pattern)


def _repair(params) -> dict:
    """لینک با «?» یا «&» اضافه (utm_source=aparat?utm_medium=social) همه‌ی مقدارها را در utm_source می‌ریزد؛ دوباره جدا می‌شود."""
    flat = {k: params.get(k) for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", *CLICK_IDS)}
    for key in [k for k in flat if k.startswith("utm_")]:
        value = flat[key] or ""
        if "?" in value or "&" in value:
            head, _, tail = value.replace("&", "?").partition("?")
            flat[key] = head
            for k, v in parse_qsl(tail.replace("?", "&")):
                if k in flat and not flat[k]:
                    flat[k] = v
    return flat


def classify(params, ref_host: str, in_app: str = "") -> dict:
    """از UTM و شناسه کلیک و Referer، منبع/نوع/کمپین را برمی‌گرداند. UTM همیشه برنده است."""
    get = _repair(params).get
    source, medium = clean(get("utm_source"), 80), clean(get("utm_medium"), 40)
    out = {"campaign": clean(get("utm_campaign"), 120), "content": clean(get("utm_content"), 120),
           "term": clean(get("utm_term"), 120), "click_id": ""}
    for cid in CLICK_IDS:
        if get(cid):
            out["click_id"] = cid
            if not source:
                source, medium = CLICK_IDS[cid][0], medium or CLICK_IDS[cid][1]
            break
    if source:
        out.update(source=source, medium=medium or "none")
        return out
    if ref_host:
        for suffix, src, med in REFERRERS:
            if _host_matches(ref_host, suffix):
                out.update(source=src, medium=med)
                return out
        out.update(source=ref_host, medium="referral")
        return out
    if in_app:
        # مرورگر داخلی بدون Referer: از همان برنامه آمده ولی لینک را نمی‌دانیم
        out.update(source=in_app, medium="social")
        return out
    out.update(source="direct", medium="none")
    return out
