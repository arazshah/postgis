"""امتیاز و فهرست کیفیت پلاگین پیش از فروش (docs/adr/0010، مرحله‌ی ۷): بررسی قطعی و بی‌مدل روی نقشه‌ی پلاگین.

- هر بررسی یک ردیف است: `{id, group, title, ok, severity, message, where, fix_ops}`؛ شدت `block` (انتشار را می‌بندد)، `warn` (باید دید) یا `info`.
- راه‌حل خودکار (`fix_ops`) فقط وقتی هست که بی‌ابهام باشد (مثل تازه‌سازی صفحه‌ی نقشه)؛ برای بقیه کاربر «رفع با دستیار» می‌زند.
- امتیاز ۰ تا ۱۰۰: هر `block` ناموفق ۳۰، هر `warn` ۶ و هر `info` ۲ نمره کم می‌کند. «قابل انتشار» یعنی هیچ `block` ناموفق نیست.
- بررسی ۴۰۰ پیکسل و اجرای آزمون‌ها به مرورگر و runner نیاز دارند و در استودیو جدا اجرا می‌شوند (این ماژول فقط مشخصات را می‌خواند).
"""
from __future__ import annotations

from . import blueprint

PENALTY = {"block": 30, "warn": 6, "info": 2}
GROUPS = (("validity", "اعتبار"), ("content", "محتوا و برچسب‌ها"), ("ux", "تجربه‌ی کاربر"), ("code", "کد و آزمون"), ("market", "بازار و دسترسی"), ("safety", "امنیت و عملیات"))
DISPLAY = ("kpi", "table", "bars", "map", "text", "sql", "handler")
WRITING = ("form", "ingest", "records", "source")
GRADES = ((90, "آماده‌ی فروش"), (70, "نزدیک به آماده"), (40, "نیازمند کار"), (0, "ناقص"))


def _pages(spec):
    return spec.get("pages") or []


def _blocks(spec):
    for p in _pages(spec):
        for b in p.get("blocks") or []:
            yield p, b


def evaluate(spec: dict, plugin_id: str) -> dict:
    """{score, grade, publishable, checks[], counts{block,warn,info}, groups[{key,label,ok,total}]}."""
    spec = blueprint.ensure_ids(spec)
    checks: list[dict] = []

    def add(cid, group, title, ok, severity, message="", where=None, fix_ops=None):
        checks.append({"id": cid, "group": group, "title": title, "ok": bool(ok), "severity": severity,
                       "message": "" if ok else message, "where": where or {}, "fix_ops": [] if ok else (fix_ops or [])})

    an = blueprint.analyze(spec, plugin_id)
    first = an["issues"][0] if an["issues"] else None
    add("valid", "validity", "پلاگین بدون ایراد ساخته می‌شود", an["ok"], "block",
        f"{len(an['issues'])} ایراد: {first['message'][:120]}" if first else "",
        {"tab": "code" if first and first["scope"] == "code" else "pages", "page": (first or {}).get("page", ""), "block": (first or {}).get("block", ""), "handler": (first or {}).get("handler", "")})

    # ---- محتوا
    add("summary", "content", "توضیح کوتاه پلاگین (کارت بازار) نوشته شده", (spec.get("intro") or {}).get("summary", "").strip(), "warn",
        "توضیح کوتاه خالی است؛ مشتری در بازار فقط همین را می‌بیند.", {"tab": "market"})
    bad = [(t["name"], c["name"]) for t in spec.get("tables") or [] for c in t.get("columns") or [] if not (c.get("label") or "").strip() and not c.get("auto_now")]
    add("labels", "content", "ستون‌ها برچسب فارسی دارند", not bad, "warn",
        f"{len(bad)} ستون برچسب فارسی ندارد (مثل «{bad[0][1]}» در {bad[0][0]})؛ در فرم و جدول نام لاتین دیده می‌شود." if bad else "", {"tab": "data"})
    untitled = [(p, b) for p, b in _blocks(spec) if b.get("kind") in ("kpi", "table", "bars", "map", "form", "records", "ingest", "source", "report") and not (b.get("title") or "").strip()]
    add("titles", "content", "بلوک‌ها عنوان دارند", not untitled, "warn",
        f"{len(untitled)} بلوک بدون عنوان است." if untitled else "", {"tab": "pages", "page": untitled[0][0]["key"] if untitled else "", "block": untitled[0][1].get("id", "") if untitled else ""})
    nosub = [p for p in _pages(spec) if not (p.get("subtitle") or "").strip()]
    add("subtitle", "content", "هر صفحه توضیح یک‌خطی دارد", not nosub, "info",
        f"{len(nosub)} صفحه توضیح یک‌خطی ندارد." if nosub else "", {"tab": "pages", "page": nosub[0]["key"] if nosub else ""})

    # ---- تجربه
    nolist = [p for p in _pages(spec) if any(b.get("kind") == "form" for b in p.get("blocks") or []) and not any(b.get("kind") in ("records", "table") for b in p.get("blocks") or [])]
    add("form_list", "ux", "صفحه‌ی فرم، فهرست ثبت‌ها را هم نشان می‌دهد", not nolist, "warn",
        f"صفحه‌ی «{nolist[0]['title']}» فرم دارد ولی جدول یا ویرایش ردیف ندارد؛ کاربر نتیجه‌ی ثبتش را نمی‌بیند." if nolist else "", {"tab": "pages", "page": nolist[0]["key"] if nolist else ""})
    live = [p for p in _pages(spec) if not p.get("refresh") and any(b.get("kind") in ("ingest", "source") for b in p.get("blocks") or [])
            and any(b.get("kind") in ("map", "kpi", "table", "bars") for b in p.get("blocks") or [])]
    add("live_refresh", "ux", "صفحه‌ی با داده‌ی زنده خودکار تازه می‌شود", not live, "warn",
        f"صفحه‌ی «{live[0]['title']}» داده‌ی زنده می‌گیرد ولی تازه‌سازی خودکار خاموش است." if live else "", {"tab": "pages", "page": live[0]["key"] if live else ""},
        [{"op": "page.set", "key": p["key"], "refresh": 15} for p in live])
    many = [p for p in _pages(spec) if len(p.get("blocks") or []) > 10]
    add("many_blocks", "ux", "صفحه‌ها طولانی نیستند", not many, "warn", f"صفحه‌ی «{many[0]['title']}» بیش از ۱۰ بلوک دارد؛ روی گوشی طولانی می‌شود." if many else "",
        {"tab": "pages", "page": many[0]["key"] if many else ""})
    nolimit = [(p, b) for p, b in _blocks(spec) if b.get("kind") == "table" and not b.get("limit")]
    add("table_limit", "ux", "جدول‌ها سقف ردیف دارند", not nolimit, "info", f"{len(nolimit)} جدول سقف ردیف ندارد (پیش‌فرض ۲۰ ردیف است).", {"tab": "pages", "page": nolimit[0][0]["key"] if nolimit else "", "block": nolimit[0][1].get("id", "") if nolimit else ""},
        [{"op": "block.set", "id": b["id"], "fields": {"limit": 20}} for _p, b in nolimit])
    used = {b.get("since_param") for _p, b in _blocks(spec)} | {w.get("param") for _p, b in _blocks(spec) for w in b.get("where") or []}
    unused = [(p, x) for p in _pages(spec) for x in p.get("params") or [] if x.get("name") not in used]
    add("params_used", "ux", "هر فیلتر صفحه به بلوکی وصل است", not unused, "warn",
        f"فیلتر «{unused[0][1].get('label')}» در صفحه‌ی «{unused[0][0]['title']}» به هیچ بلوکی وصل نیست." if unused else "", {"tab": "pages", "page": unused[0][0]["key"] if unused else ""})

    # ---- کد
    code = spec.get("code") or {}
    thin = [n for n, h in code.items() if len(h.get("cases") or []) < 2 and (h.get("cases") or h.get("test"))]
    add("code_cases", "code", "هر کد دست‌کم دو مورد آزمون دارد (عادی و مرزی)", not thin, "warn", f"کد «{thin[0]}» فقط یک مورد آزمون دارد؛ حالت خالی یا مرزی را هم بیفزایید." if thin else "", {"tab": "code", "handler": thin[0] if thin else ""})
    unwired = [n for n, h in code.items() if h.get("role") in ("block", "importer", "exporter", "ingest")
               and not any(b.get("handler") == n for _p, b in _blocks(spec))]
    add("code_wired", "code", "هر کد به صفحه وصل است", not unwired, "warn", f"کد «{unwired[0]}» در هیچ صفحه‌ای استفاده نشده." if unwired else "", {"tab": "code", "handler": unwired[0] if unwired else ""})

    # ---- بازار
    acc = spec.get("access") or {}
    add("access", "market", "دسترسی و قیمت تنظیم شده", bool(acc.get("mode")), "warn", "هنوز «عمومی رایگان / عمومی پولی / اختصاصی» انتخاب نشده است.", {"tab": "market"})
    lst = spec.get("listing") or {}
    add("listing", "market", "آگهی بازار کامل است (دسته و ویژگی‌ها)", not (acc.get("mode") == "public_paid" and (not lst.get("category") or len(lst.get("features") or []) < 2)), "warn",
        "برای پلاگین پولی دسته و دست‌کم دو ویژگی بنویسید تا در بازار پیدا و فهمیده شود.", {"tab": "market"})
    add("trial", "market", "پلاگین پولی دوره‌ی آزمایشی دارد", not (acc.get("mode") == "public_paid" and not int(acc.get("trial_days") or 0)), "info",
        "مشتری بدون آزمایش کمتر می‌خرد؛ چند روز آزمایشی رایگان در نظر بگیرید.", {"tab": "market"})

    # ---- امنیت و عملیات
    sql = [(p, b) for p, b in _blocks(spec) if b.get("kind") == "sql"]
    add("raw_sql", "safety", "SQL پیشرفته دستی بازبینی شده", not sql, "info", f"{len(sql)} بلوک «SQL پیشرفته» هست؛ فقط‌خواندنی است ولی سنگینی و درستی‌اش را دستی ببینید.",
        {"tab": "pages", "page": sql[0][0]["key"] if sql else "", "block": sql[0][1].get("id", "") if sql else ""})
    src = [(p, b) for p, b in _blocks(spec) if b.get("kind") == "source"]
    add("source_hosts", "safety", "میزبان منبع بیرونی تأیید شده", not src, "info", "منبع بیرونی دارید؛ میزبانش باید در پنل «منابع بیرونی» تأیید و سوئیچش روشن باشد وگرنه واکشی نمی‌شود.",
        {"tab": "pages", "page": src[0][0]["key"] if src else "", "block": src[0][1].get("id", "") if src else ""})
    writers = [p for p in _pages(spec) if any(b.get("kind") in WRITING for b in p.get("blocks") or []) and p.get("need") == "viewer"]
    add("write_need", "safety", "صفحه‌ی نویسنده سطح دسترسی درست دارد", not writers, "info", f"صفحه‌ی «{writers[0]['title']}» می‌نویسد؛ سطح «بیننده» خودکار «ویرایشگر» می‌شود، صریح بنویسید." if writers else "",
        {"tab": "pages", "page": writers[0]["key"] if writers else ""}, [{"op": "page.set", "key": p["key"], "need": "editor"} for p in writers])

    counts = {"block": 0, "warn": 0, "info": 0}
    penalty = 0
    for c in checks:
        if not c["ok"]:
            counts[c["severity"]] += 1
            penalty += PENALTY[c["severity"]]
    score = max(0, 100 - penalty)
    grade = next(label for floor, label in GRADES if score >= floor)
    if counts["block"] and score >= 70:
        grade = "نیازمند کار"
    groups = [{"key": k, "label": label, "ok": sum(1 for c in checks if c["group"] == k and c["ok"]), "total": sum(1 for c in checks if c["group"] == k)} for k, label in GROUPS]
    return {"score": score, "grade": grade, "publishable": not counts["block"], "checks": checks, "counts": counts, "groups": groups}


def summary(spec: dict, plugin_id: str) -> dict:
    q = evaluate(spec, plugin_id)
    return {"score": q["score"], "grade": q["grade"], "publishable": q["publishable"], "counts": q["counts"]}
