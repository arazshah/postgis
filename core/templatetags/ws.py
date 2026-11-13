"""منوی کنار صفحه برای همه بخش‌های یک پایگاه داده (فضای کار): دسته‌بندی ثابت، بخش فعلی مشخص."""
import logging

from django import template
from django.urls import reverse

from kernel import entitlements, nav
from kernel import jobs as kernel_jobs

register = template.Library()

# مسیرهای قدیمی (برای آیکون‌های قدیمی داشبورد)؛ آیکون‌های تازه از core/icons.py می‌آیند
ICONS = {
    "home": "M3 11l9-8 9 8M5 10v10h14V10",
    "tables": "M3 5h18v14H3zM3 10h18M9 5v14",
    "sql": "M8 8l-4 4 4 4M16 8l4 4-4 4M13 6l-2 12",
    "import": "M12 3v12M7 10l5 5 5-5M4 21h16",
    "pin": "M12 21s7-6 7-11a7 7 0 10-14 0c0 5 7 11 7 11zM12 12a2 2 0 100-4 2 2 0 000 4",
    "health": "M3 12h4l3-8 4 16 3-8h4",
    "chart": "M4 20V10M10 20V4M16 20v-7M22 20H2",
    "globe": "M12 3a9 9 0 100 18 9 9 0 000-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18",
    "layers": "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5",
    "map": "M9 4L3 6v14l6-2 6 2 6-2V4l-6 2zM9 4v14M15 6v14",
    "code": "M9 4C6 4 7 9 5 12c2 3 1 8 4 8M15 4c3 0 2 5 4 8-2 3-1 8-4 8",
    "team": "M16 19v-1a4 4 0 00-4-4H8a4 4 0 00-4 4v1M10 11a3 3 0 100-6 3 3 0 000 6M20 19v-1a3 3 0 00-2-3M16 5a3 3 0 010 6",
    "backup": "M4 7c0-2 16-2 16 0v10c0 2-16 2-16 0zM4 12c0 2 16 2 16 0",
    "gauge": "M4 18a8 8 0 1116 0M12 18l4-6",
    "survey": "M12 3v18M3 12h18M7 7l10 10M17 7L7 17",
    "building": "M3 21V8l9-5 9 5v13M9 21v-6h6v6",
    "plug": "M9 2v5M15 2v5M6 7h12v4a6 6 0 01-12 0zM12 17v5",
    "plus": "M12 5v14M5 12h14",
    "alert": "M12 3l10 18H2zM12 10v5M12 18v.5",
    "clock": "M12 3a9 9 0 100 18 9 9 0 000-18zM12 7v5l3 2",
    "check": "M5 12l5 5 9-10",
    "school": "M2 9l10-5 10 5-10 5zM6 11v5c3 2 9 2 12 0v-5",
    "arrow": "M19 12H5M11 6l-6 6 6 6",
}

LEVEL = {"viewer": 0, "editor": 1, "owner": 2}


def _visible(item, ws=None) -> bool:
    """بخش دیده شود؟ شرط ثبت‌شده‌ی خودش + روشن بودن پلاگین و مجوز آن برای این فضای کار (kernel.entitlements)."""
    if item.visible:
        try:
            if not kernel_jobs.call(item.visible):
                return False
        except Exception:  # noqa: BLE001  شرط معیوب یک پلاگین نباید همه‌ی صفحه‌های فضای کار را بشکند؛ آن بخش پنهان می‌شود
            logging.getLogger(__name__).exception("visible of %s failed", item.plugin)
            from kernel import health

            health.contribution_failed(item.plugin)
            return False
    return entitlements.allowed(item.plugin, ws=ws)


def groups():
    """(عنوان گروه، [(عنوان، url name، نام viewها، آیکون، حداقل دسترسی)]) از بخش‌هایی که پلاگین‌ها ثبت کرده‌اند."""
    return [(g.title, [(s.label, s.url, s.views, s.icon, s.need) for s in items]) for g, items in nav.ws_groups()]


def dash_groups():
    """(کلید گروه، عنوان، [(عنوان، توضیح، url name، آیکون)]) برای کارت‌های میانبر خانه."""
    return [(g.key, g.title, [(a.label, a.hint, a.url, a.icon) for a in items]) for g, items in nav.home_groups()]


def __getattr__(name):  # سازگاری: ws.GROUPS و ws.DASH_GROUPS همان شکل قبلی را دارند
    if name == "GROUPS":
        return groups()
    if name == "DASH_GROUPS":
        return dash_groups()
    raise AttributeError(name)


def build(db, view_name: str, kwargs: dict | None = None) -> dict:
    mine = bool(getattr(db, "is_mine", False))
    level = 2 if mine else (1 if getattr(db, "can_edit", False) else 0)
    out, current = [], None
    for g, items in nav.ws_groups():
        rows, has_current = [], False
        for s in items:
            if LEVEL[s.need] > level or not _visible(s, db):
                continue
            on = view_name in s.views and (not s.extra or tuple(str((kwargs or {}).get(k)) for k in ("plugin", "page")) == tuple(map(str, s.extra)))
            row = {"label": s.label, "url": s.url, "extra": s.extra, "on": on, "icon": s.icon,
                   "href": reverse(s.url, args=[db.pk, *s.extra])}
            rows.append(row)
            if on:
                current, has_current = row, True
        if rows:
            out.append({"title": g.title, "key": g.key, "items": rows, "has_current": has_current})
    return {"groups": out, "current": current}


MAX_SWITCH = 60


def _other_databases(user, db) -> list:
    """پایگاه‌های داده‌ی دیگر کاربر (خودش + اشتراکی) برای تعویض سریع؛ خود پایگاه فعلی در فهرست نیست."""
    from databases.models import UserDatabase
    from kernel import workspace

    if not getattr(user, "is_authenticated", False):
        return []
    mine = list(user.databases.exclude(status=UserDatabase.Status.DELETED).order_by("db_name")[:MAX_SWITCH])
    seen = {d.pk for d in mine}
    shared = [d for d in workspace.shared_with(user).order_by("db_name")[:MAX_SWITCH] if d.pk not in seen]
    out = []
    for d in mine + shared:
        if d.pk != db.pk:
            out.append({"pk": d.pk, "name": d.db_name, "live": d.is_live, "mine": d.pk in seen})
    return out[:MAX_SWITCH]


def switch_targets(user, db, current) -> list:
    """هر پایگاه را به همان بخشی که کاربر الان در آن است می‌برد؛ اگر پایگاه فعال نیست، به نمای کلی‌اش."""
    section = current["url"] if current else "databases:detail"
    extra = current.get("extra", ()) if current else ()
    rows = []
    for o in _other_databases(user, db):
        url = reverse(section if o["live"] else "databases:detail", args=[o["pk"], *(extra if o["live"] else ())])
        rows.append({"name": o["name"], "url": url, "mine": o["mine"], "live": o["live"]})
    return rows


def jump_entries(db, groups, switch) -> list:
    """فهرست پرش سریع (Ctrl+K): بخش‌های همین پایگاه + سایر پایگاه‌ها."""
    out = []
    for g in groups:
        for it in g["items"]:
            out.append({"t": it["label"], "u": it["href"], "g": g["title"] or "پایگاه داده", "k": "s"})
    for o in switch:
        out.append({"t": o["name"], "u": o["url"], "g": "رفتن به پایگاه داده", "k": "d"})
    return out


@register.inclusion_tag("databases/_ws_nav.html", takes_context=True)
def ws_nav(context, db):
    request = context.get("request")
    name = request.resolver_match.view_name if request and request.resolver_match else ""
    data = build(db, name, request.resolver_match.kwargs if request and request.resolver_match else None)
    switch = switch_targets(request.user, db, data["current"]) if request else []
    return {"db": db, "groups": data["groups"], "current": data["current"], "switch": switch,
            "jump": jump_entries(db, data["groups"], switch)}


@register.simple_tag(takes_context=True)
def ws_title(context, db):
    request = context.get("request")
    name = request.resolver_match.view_name if request and request.resolver_match else ""
    cur = build(db, name, request.resolver_match.kwargs if request and request.resolver_match else None)["current"]
    return cur["label"] if cur else ""


@register.simple_tag
def icon(name, size=20, cls=""):
    """آیکون خطی (SVG درون‌خطی) از مجموعه‌ی سیستم طراحی (core/icons.py)؛ نام ناشناخته‌ی قدیمی از مسیرهای قدیمی می‌خواند."""
    from django.utils.html import format_html
    from django.utils.safestring import mark_safe

    from core.icons import ICONS as SET

    inner = SET.get(name)
    if inner is None:
        inner = format_html('<path d="{}"/>', ICONS.get(name, ""))
    return format_html(
        '<svg class="i {2}" width="{0}" height="{0}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{1}</svg>',
        size, mark_safe(inner), cls)  # noqa: S308 (مجموعه‌ی ثابت داخل مخزن)


@register.inclusion_tag("databases/_dash_actions.html")
def dash_actions(db):
    """کارت‌های میانبر خانه: هر دکمه یک عنوان کوتاه + یک جمله که دقیقاً می‌گوید چه می‌کند."""
    out = []
    for g, items in nav.home_groups():
        out.append({"key": g.key, "title": g.title, "items": [
            {"label": a.label, "hint": a.hint, "url": reverse(a.url, args=[db.pk]), "icon": a.icon}
            for a in items if _visible(a, db)]})
    return {"groups": out}


@register.inclusion_tag("databases/_dash_menu.html")
def dash_menu(db):
    """منوی «⋯» ردیف فشرده‌ی داشبورد: همه‌ی بخش‌ها با همان دسته‌بندی منوی کنار صفحه (فقط پایگاه‌های خود کاربر)."""
    out = []
    for g, items in nav.ws_groups():
        rows = [{"label": s.label, "url": reverse(s.url, args=[db.pk, *s.extra])} for s in items if _visible(s, db)]
        if rows:
            out.append({"title": g.title, "items": rows})
    return {"groups": out}


# نوار تب پایین گوشی: چهار بخش پرکاربرد (فقط آن‌هایی که کاربر به آن‌ها دسترسی دارد) + «بیشتر»
TAB_VIEWS = ("databases:detail", "databases:explore", "maps:index", "analysis:page")
TAB_LABELS = {"databases:detail": "نمای کلی", "databases:explore": "جدول‌ها", "maps:index": "نقشه‌ها", "analysis:page": "تحلیل"}


@register.inclusion_tag("databases/_ws_tabs.html", takes_context=True)
def ws_tabs(context, db):
    request = context.get("request")
    name = request.resolver_match.view_name if request and request.resolver_match else ""
    data = build(db, name, request.resolver_match.kwargs if request and request.resolver_match else None)
    rows = {it["url"]: it for g in data["groups"] for it in g["items"]}
    tabs = [{"label": TAB_LABELS[u], "url": reverse(u, args=[db.pk]), "icon": rows[u]["icon"], "on": rows[u]["on"]}
            for u in TAB_VIEWS if u in rows]
    return {"tabs": tabs}
