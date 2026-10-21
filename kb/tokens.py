"""توکن‌های پویا در متن مقاله‌ها: مقدارهایی که ممکن است عوض شوند (پلن، مهلت‌ها، پشتیبانی) در متن ثابت نوشته
نمی‌شوند و هنگام نمایش و خروجی از تنظیمات و پلن‌ها خوانده می‌شوند. نمونه: {{plan_quota}} یا {{plans_table}}."""
from __future__ import annotations

import re

from django.conf import settings

_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
TOKEN_RE = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")


def fanum(value) -> str:
    return str(value).translate(_FA)


def _toman(n: int) -> str:
    return fanum(f"{n:,}").replace(",", "٬") + " تومان"


def _plan_values(plan) -> dict[str, str]:
    from databases.defaults import FREE_PLAN

    def g(name, default):
        return getattr(plan, name, None) if plan is not None else FREE_PLAN.get(name, default)

    quota_mb = g("quota_mb", 1024)
    quota = f"{quota_mb // 1024} گیگابایت" if quota_mb >= 1024 and quota_mb % 1024 == 0 else f"{quota_mb} مگابایت"
    return {
        "plan_name": str(g("name", "رایگان")),
        "plan_quota": fanum(quota),
        "plan_connections": fanum(g("max_connections", 5)),
        "plan_days": fanum(g("duration_days", 90)),
        "plan_timeout": fanum(g("statement_timeout_s", 60)),
        "plan_backup_days": fanum(g("backup_retention_days", 3)),
        "plan_layers": fanum(g("publish_layers", 3)),
        "plan_daily_requests": fanum(f"{g('publish_daily_requests', 5000):,}").replace(",", "٬"),
        "plan_ows_projects": fanum(g("ows_projects", 1)),
        "plan_db_roles": fanum(g("db_roles", 1)),
        "plan_team_members": fanum(g("team_members", 0)),
    }


def plans_table() -> str:
    from databases.models import Plan

    plans = list(Plan.objects.filter(is_public=True))
    if not plans:
        return "_فهرست پلن‌ها هنوز ثبت نشده است._"
    rows = ["| پلن | حجم | اتصال همزمان | اعتبار | قیمت |", "|---|---|---|---|---|"]
    for p in plans:
        price = "رایگان" if p.is_free or not p.price_toman else _toman(p.price_toman)
        rows.append(f"| {p.name} | {fanum(p.quota_display)} | {fanum(p.max_connections)} | "
                    f"{fanum(p.duration_days)} روز | {price} |")
    return "\n".join(rows)


def values() -> dict[str, str]:
    """همه توکن‌های ساده؛ هر بار از پایگاه داده تازه خوانده می‌شود."""
    from core.models import SiteSettings
    from databases.models import Plan

    conf = SiteSettings.get()
    plan = Plan.objects.filter(is_default=True).first() or Plan.objects.filter(is_free=True).first()
    out = _plan_values(plan)
    out.update({
        "site_name": conf.site_name,
        "site_url": settings.CANONICAL_URL,
        "support_phone": conf.support_phone or "—",
        "support_telegram": f"@{conf.support_telegram}" if conf.support_telegram else "—",
        "support_email": conf.support_email or "—",
        "expiry_warning_days": fanum(conf.expiry_warning_days),
        "grace_days": fanum(conf.expired_grace_days),
        "renew_window_days": fanum(conf.renew_window_days),
        "invoice_ttl_minutes": fanum(conf.invoice_ttl_minutes),
        "max_databases": fanum(conf.max_databases_per_user),
    })
    return out


KNOWN = {"plans_table", *(_plan_values(None).keys()),
         "site_name", "site_url", "support_phone", "support_telegram", "support_email",
         "expiry_warning_days", "grace_days", "renew_window_days", "invoice_ttl_minutes", "max_databases"}


def unknown_tokens(text: str) -> set[str]:
    return {m for m in TOKEN_RE.findall(text or "") if m not in KNOWN}


def resolve(text: str, vals: dict[str, str] | None = None) -> str:
    """جایگزینی توکن‌ها؛ توکن ناشناس دست‌نخورده می‌ماند تا اشتباه تایپی دیده شود."""
    if not text or "{{" not in text:
        return text or ""
    vals = vals if vals is not None else values()
    table = None

    def sub(m):
        nonlocal table
        key = m.group(1)
        if key == "plans_table":
            if table is None:
                table = plans_table()
            return table
        return vals.get(key, m.group(0))

    return TOKEN_RE.sub(sub, text)


_LINK_RE = re.compile(r"\]\((kb|help|doc):([a-z0-9][a-z0-9-]*)(#[^)\s]*)?\)")
_LINK_ROUTES = {"kb": "/kb/{}/", "help": "/help/{}/", "doc": "/docs/{}/"}


def expand_links(text: str, base: str = "") -> str:
    """میان‌بر پیوند: [متن](kb:slug) مقاله، [متن](help:slug) راهنمای تصویری، [متن](doc:slug) آموزش.
    در خروجی ماشینی با base=آدرس سایت، پیوند مطلق می‌شود."""
    def sub(m):
        return f"]({base}{_LINK_ROUTES[m.group(1)].format(m.group(2))}{m.group(3) or ''})"

    return _LINK_RE.sub(sub, text or "")


def link_targets(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in _LINK_RE.finditer(text or "")]
