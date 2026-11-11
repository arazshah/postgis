"""ناوبری پنل مدیریت: گروه‌بندی بخش‌ها بر اساس کار روزانه‌ی مدیر (نه بر اساس برنامه‌ی جنگو).

هر بخش `app_label.model` است؛ بخشی که در این فهرست نیامده باشد خودکار در گروه «سایر» می‌آید تا چیزی گم نشود.
"""
from django.contrib import admin
from django.urls import NoReverseMatch, reverse

from kernel import nav
from kernel.jobs import load


def _find(label):
    for model, ma in admin.site._registry.items():
        if f"{model._meta.app_label}.{model._meta.model_name}" == label:
            return model, ma
    return None, None


def _url(model, view="changelist"):
    try:
        return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_{view}")
    except NoReverseMatch:
        return ""


def badges():
    """شمارنده‌ی کارهای منتظر مدیر: label مدل ← عدد (هر پلاگین شمارنده‌ی خودش را ثبت می‌کند)."""
    out = {}
    for label, counter in nav.admin_badges().items():
        try:
            out[label] = int(load(counter)())
        except Exception:  # noqa: BLE001  شمارنده نباید صفحه را بشکند
            continue
    return out


def __getattr__(name):  # سازگاری با مصرف‌کننده‌های قدیمی
    if name == "QUICK":
        return [(q.label, q.icon, q.url) for q in nav.admin_quicks()]
    if name == "GROUPS":
        return [(g.key, g.title, g.icon, [(i.model, i.title) for i in items]) for g, items in nav.admin_groups()]
    raise AttributeError(name)


def build(request):
    """گروه‌های ناوبری مجاز برای این کاربر؛ بخش فعال با تطبیق مسیر مشخص می‌شود."""
    path = request.path
    counts = badges()
    used, groups = set(), []
    perm_ok = lambda ma: ma.has_module_permission(request) and ma.has_view_or_change_permission(request)  # noqa: E731

    def item(label, title, model, ma):
        url = _url(model)
        base = url
        return {"label": label, "title": title or str(model._meta.verbose_name_plural), "url": url,
                "on": bool(base) and path.startswith(base), "count": counts.get(label, 0)}

    for key, title, icon, rows in __getattr__("GROUPS"):
        items = []
        for label, name in rows:
            model, ma = _find(label)
            used.add(label)
            if model is None or not perm_ok(ma):
                continue
            it = item(label, name, model, ma)
            if it["url"]:
                items.append(it)
        if items:
            groups.append({"key": key, "title": title, "icon": icon, "items": items,
                           "on": any(i["on"] for i in items), "count": sum(i["count"] for i in items)})
    rest = []
    for model, ma in admin.site._registry.items():
        label = f"{model._meta.app_label}.{model._meta.model_name}"
        if label in used or not perm_ok(ma):
            continue
        it = item(label, None, model, ma)
        if it["url"]:
            rest.append(it)
    if rest:
        groups.append({"key": "other", "title": "سایر", "icon": "cube", "items": rest,
                       "on": any(i["on"] for i in rest), "count": 0})
    return groups


def palette(groups, request):
    """فهرست مسطح برای جست‌وجوی Ctrl+K (بخش‌ها و کارهای سریع)."""
    rows = [{"t": "داشبورد", "u": reverse("admin:index"), "g": "خانه", "i": "dash"}]
    for g in groups:
        for it in g["items"]:
            rows.append({"t": it["title"], "u": it["url"], "g": g["title"], "i": g["icon"]})
            model, ma = _find(it["label"])
            if model is not None:
                add = _url(model, "add")
                if add and ma.has_add_permission(request):
                    rows.append({"t": f"افزودن — {it['title']}", "u": add, "g": g["title"], "i": "plus"})
    return rows

