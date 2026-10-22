"""منوی کنار صفحه برای همه بخش‌های یک پایگاه داده (فضای کار): دسته‌بندی ثابت، بخش فعلی مشخص."""
from django import template

register = template.Library()

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
    "building": "M3 21V8l9-5 9 5v13M9 21v-6h6v6",
}

# (کلید گروه، عنوان، [(نام view برای تشخیص بخش فعال…, عنوان، url name، آیکون، حداقل دسترسی)])
GROUPS = [
    ("", [("نمای کلی و اتصال", "databases:detail", ("databases:detail",), "home", "viewer")]),
    ("داده", [
        ("جدول‌ها", "databases:explore", ("databases:explore", "databases:explore_table"), "tables", "viewer"),
        ("اجرای SQL", "databases:explore_sql", ("databases:explore_sql",), "sql", "viewer"),
        ("ورود فایل", "databases:import", ("databases:import", "databases:import_review"), "import", "editor"),
        ("داده آماده ایران", "iranmap:ready", ("iranmap:ready",), "pin", "editor"),
        ("سلامت داده", "databases:explore_health", ("databases:explore_health",), "health", "viewer"),
    ]),
    ("تحلیل و انتشار", [
        ("تحلیل", "analysis:page", ("analysis:page",), "chart", "editor"),
        ("نقشه‌های چندلایه", "maps:index", ("maps:index", "maps:composer", "maps:quick"), "map", "viewer"),
        ("نقشه و API", "publish:manage", ("publish:manage", "publish:map_builder"), "globe", "editor"),
        ("WMS و WFS", "publish:ows", ("publish:ows", "publish:ows_detail"), "layers", "editor"),
        ("REST API و فرم میدانی", "restapi:manage", ("restapi:manage",), "code", "editor"),
    ]),
    ("مدیریت", [
        ("تیم و کاربران", "databases:team", ("databases:team",), "team", "owner"),
        ("بکاپ و بازگردانی", "databases:backups", ("databases:backups",), "backup", "owner"),
        ("مصرف و کارایی", "databases:usage", ("databases:usage",), "gauge", "owner"),
        ("امکانات سازمانی", "enterprise:page", ("enterprise:page",), "building", "owner"),
    ]),
]
LEVEL = {"viewer": 0, "editor": 1, "owner": 2}


def build(db, view_name: str) -> dict:
    mine = bool(getattr(db, "is_mine", False))
    level = 2 if mine else (1 if getattr(db, "can_edit", False) else 0)
    groups, current = [], None
    for title, items in GROUPS:
        rows = []
        for label, url, views, icon, need in items:
            if LEVEL[need] > level:
                continue
            on = view_name in views
            row = {"label": label, "url": url, "on": on, "icon": ICONS[icon]}
            rows.append(row)
            if on:
                current = row
        if rows:
            groups.append({"title": title, "items": rows})
    return {"groups": groups, "current": current}


@register.inclusion_tag("databases/_ws_nav.html", takes_context=True)
def ws_nav(context, db):
    request = context.get("request")
    name = request.resolver_match.view_name if request and request.resolver_match else ""
    data = build(db, name)
    return {"db": db, "groups": data["groups"], "current": data["current"]}


@register.simple_tag(takes_context=True)
def ws_title(context, db):
    request = context.get("request")
    name = request.resolver_match.view_name if request and request.resolver_match else ""
    cur = build(db, name)["current"]
    return cur["label"] if cur else ""
