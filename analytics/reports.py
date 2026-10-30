"""گزارش‌های منبع ورود. همه بر پایه منبع اولین ورود (first-touch) بازدیدکننده‌اند."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from . import quality
from .models import Event, Visitor

RANGES = (7, 30, 90)


def _pct(a: int, b: int) -> str:
    return f"{a * 100 / b:.1f}٪".replace(".", "٫") if b else "—"


def breakdown(fields: list[str], days: int, limit: int = 30) -> list[dict]:
    """بازدیدکننده‌های جدید این بازه، گروه‌بندی‌شده با قیف ثبت‌نام."""
    since = timezone.now() - timedelta(days=days)
    base = Visitor.objects.filter(first_seen__gte=since, flag="")
    rows = {tuple(r[f] for f in fields): {"visitors": r["n"]}
            for r in base.values(*fields).annotate(n=Count("id"))}
    ev = (Event.objects.filter(visitor__first_seen__gte=since, visitor__flag="")
          .values(*[f"visitor__{f}" for f in fields], "name").annotate(n=Count("visitor", distinct=True)))
    for r in ev:
        key = tuple(r[f"visitor__{f}"] for f in fields)
        if key in rows:
            rows[key][r["name"]] = r["n"]
    out = []
    for key, d in rows.items():
        visitors = d["visitors"]
        req, ver = d.get(Event.OTP_REQUESTED, 0), d.get(Event.OTP_VERIFIED, 0)
        signup, dbs = d.get(Event.SIGNUP, 0), d.get(Event.DB_CREATED, 0)
        out.append({
            "keys": key, "label": " / ".join(k or "—" for k in key), "visitors": visitors, "requested": req,
            "verified": ver, "signup": signup, "dbs": dbs, "stuck": max(req - ver, 0),
            "send_failed": d.get(Event.OTP_SEND_FAILED, 0), "wrong": d.get(Event.OTP_WRONG, 0),
            "signup_rate": _pct(signup, visitors), "request_rate": _pct(req, visitors),
            "db_rate": _pct(dbs, visitors),
        })
    out.sort(key=lambda r: (-r["visitors"], r["label"]))
    return out[:limit]


def funnel(days: int) -> list[dict]:
    since = timezone.now() - timedelta(days=days)
    visitors = Visitor.objects.filter(first_seen__gte=since, flag="").count()

    def count(name):
        return (Event.objects.filter(visitor__first_seen__gte=since, visitor__flag="", name=name)
                .values("visitor").distinct().count())

    steps = [("بازدیدکننده", visitors), ("درخواست کد ورود", count(Event.OTP_REQUESTED)),
             ("ورود کد صحیح", count(Event.OTP_VERIFIED)), ("ثبت‌نام جدید", count(Event.SIGNUP)),
             ("ساخت پایگاه داده", count(Event.DB_CREATED)), ("ورود اولین داده", count(Event.IMPORT_QUEUED)),
             ("دیدن داده روی نقشه", count(Event.MAP_VIEWED))]
    out, prev = [], None
    for label, n in steps:
        out.append({"label": label, "n": n, "of_total": _pct(n, visitors), "of_prev": _pct(n, prev) if prev else "—",
                    "width": int(n * 100 / visitors) if visitors else 0})
        prev = n
    return out


def build(days: int) -> dict:
    days = days if days in RANGES else 30
    quality.refresh()
    return {
        "excluded": quality.excluded_counts(days),
        "days": days, "ranges": RANGES, "funnel": funnel(days),
        "sources": breakdown(["first_source", "first_medium", "first_campaign"], days),
        "landing": breakdown(["first_landing"], days, 15),
        "referrers": breakdown(["first_referrer"], days, 15),
        "devices": breakdown(["device"], days, 5),
        "in_app": [r for r in breakdown(["in_app"], days, 8) if r["keys"][0]],
    }
