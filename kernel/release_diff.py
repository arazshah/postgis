"""مقایسه‌ی دو نسخه‌ی پلاگین برای استودیو (docs/adr/0010 مرحله‌ی ۸): «چه چیزی تغییر کرد» به زبان کاربر، از روی خود بسته (نه از نقشه).

خلاصه‌ی هر نسخه از فایل‌های بسته ساخته می‌شود: صفحه‌ها و بلوک‌ها، جدول‌ها و ستون‌ها، handlerها و آزمون‌ها؛ تفاضل فهرست پیام فارسی است.
فقط می‌خواند؛ چیزی اجرا نمی‌شود.
"""
from __future__ import annotations

import hashlib
import tomllib

from . import pkg

KIND_FA = {"kpi": "شمارنده", "table": "جدول", "bars": "میله‌ای", "map": "نقشه", "text": "متن"}
PART_FA = {"forms": "فرم", "ingest": "دریافت از دستگاه", "records": "ویرایش ردیف", "sources": "منبع بیرونی", "reports": "گزارش PDF",
           "imports": "ورود فایل", "exports": "خروجی فایل", "params": "فیلتر"}


def files_of(release) -> dict[str, bytes]:
    return pkg.read_archive(bytes(release.blob))


def summarize(files: dict[str, bytes]) -> dict:
    """{version, pages{key: {title, blocks{kind: n}, parts{name: n}}}, tables{name: [cols]}, handlers{name: sha}, tests{name: n}}."""
    out: dict = {"version": "", "pages": {}, "tables": {}, "handlers": {}, "tests": {}}
    try:
        out["version"] = str(tomllib.loads(files.get(pkg.MANIFEST_NAME, b"").decode("utf-8", "replace")).get("version", ""))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        pass
    for name, data in files.items():
        try:
            if name.startswith("pages/") and name.endswith(".toml"):
                d = tomllib.loads(data.decode("utf-8", "replace"))
                blocks: dict[str, int] = {}
                for b in d.get("blocks") or []:
                    k = "کد" if b.get("handler") else b.get("kind", "؟")
                    blocks[k] = blocks.get(k, 0) + 1
                out["pages"][d.get("key") or name[6:-5]] = {"title": d.get("title", ""), "blocks": blocks,
                                                           "parts": {p: len(d.get(p) or []) for p in PART_FA if d.get(p)}}
                for t in d.get("tables") or []:
                    out["tables"][t["name"]] = [c["name"] for c in t.get("columns") or []]
            elif name.startswith("code/") and name.endswith(".py"):
                out["handlers"][name[5:-3]] = hashlib.sha256(data).hexdigest()[:12]
            elif name.startswith("tests/") and name.endswith(".toml"):
                out["tests"][name[6:-5]] = len(tomllib.loads(data.decode("utf-8", "replace")).get("cases") or [])
        except (tomllib.TOMLDecodeError, KeyError, TypeError, AttributeError):
            continue
    return out


def _blocks_text(b: dict) -> str:
    return "، ".join(f"{n} {KIND_FA.get(k, k)}" for k, n in sorted(b.items())) or "بدون بلوک"


def diff(old: dict, new: dict) -> list[dict]:
    """[{kind: add|remove|change, text}]؛ خالی = بدون تغییر در صفحه‌ها، جدول‌ها و کد."""
    out: list[dict] = []

    def add(kind, text):
        out.append({"kind": kind, "text": text})

    for k, p in new["pages"].items():
        if k not in old["pages"]:
            add("add", f"صفحه‌ی «{p['title']}» اضافه شد ({_blocks_text(p['blocks'])})")
            continue
        o = old["pages"][k]
        if o["title"] != p["title"]:
            add("change", f"عنوان صفحه از «{o['title']}» به «{p['title']}» تغییر کرد")
        if o["blocks"] != p["blocks"]:
            add("change", f"صفحه‌ی «{p['title']}»: بلوک‌ها از ({_blocks_text(o['blocks'])}) به ({_blocks_text(p['blocks'])}) رسید")
        for part, label in PART_FA.items():
            a, b = o["parts"].get(part, 0), p["parts"].get(part, 0)
            if a != b:
                add("add" if b > a else "remove", f"صفحه‌ی «{p['title']}»: {label} از {a} به {b}")
    for k, o in old["pages"].items():
        if k not in new["pages"]:
            add("remove", f"صفحه‌ی «{o['title']}» حذف شد")
    for t, cols in new["tables"].items():
        if t not in old["tables"]:
            add("add", f"جدول «{t}» اضافه شد ({len(cols)} ستون)")
        else:
            added = [c for c in cols if c not in old["tables"][t]]
            gone = [c for c in old["tables"][t] if c not in cols]
            if added:
                add("add", f"جدول «{t}»: ستون {'، '.join(added)} اضافه شد (در پایگاه مشتری فقط افزوده می‌شود)")
            if gone:
                add("remove", f"جدول «{t}»: ستون {'، '.join(gone)} از تعریف برداشته شد (در پایگاه مشتری می‌ماند)")
    for t in old["tables"]:
        if t not in new["tables"]:
            add("remove", f"جدول «{t}» از تعریف برداشته شد (داده‌ی مشتری حذف نمی‌شود)")
    for h, sha in new["handlers"].items():
        if h not in old["handlers"]:
            add("add", f"کد «{h}» اضافه شد")
        elif old["handlers"][h] != sha:
            add("change", f"کد «{h}» تغییر کرد")
    for h in old["handlers"]:
        if h not in new["handlers"]:
            add("remove", f"کد «{h}» حذف شد")
    for h, n in new["tests"].items():
        if old["tests"].get(h, n) != n:
            add("change", f"آزمون‌های «{h}» از {old['tests'][h]} به {n} مورد رسید")
    return out
