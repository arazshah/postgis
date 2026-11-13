"""نقشه‌ی پلاگین و عملیات روی آن (docs/adr/0010): هر تغییر استودیوی دیداری یک «عملیات» کوچک و اعتبارسنجی‌شده است.

- نقشه همان مشخصات ویزارد است (`PluginDraft.wizard`: intro، tables، pages، code، access)؛ فقط هر صفحه و بلوک شناسه‌ی پایدار `id` می‌گیرد.
- `apply(spec, plugin_id, op)` نقشه‌ی **تازه** برمی‌گرداند (ورودی دست‌نخورده)؛ خطای ساختاری = `BlueprintError` با پیام فارسی.
  ایراد معنایی بلوک (ستون نبودن، جدول انتخاب‌نشده…) مانع عملیات نیست و در `analyze` به‌صورت `issues` می‌آید؛ انتشار فقط بدون ایراد است.
- بدون وابستگی به جنگو. رابط، کشیدن و رها کردن و دستیار هوش مصنوعی همه همین عملیات را می‌فرستند.
"""
from __future__ import annotations

import copy
import re
import secrets
from typing import Any

from . import market, wizard, wizard_code

MAX_PAGES = wizard.MAX_PAGES
MAX_BLOCKS = 24  # سقف کیت صفحه (pagekit.parse_page)
WIDTHS = ("full", "half", "third")
GROUPS = ("data", "share", "manage")
NEEDS = ("viewer", "editor", "owner")
PAGE_FIELDS = ("title", "subtitle", "icon", "group", "need", "refresh", "params")
BLOCK_STR_LIMIT = 4000
ID_RE = re.compile(r"^[a-z][a-z0-9]{3,11}$")


class BlueprintError(ValueError):
    """پیام فارسی کوتاه برای کاربر استودیو."""


def new_id() -> str:
    return "b" + secrets.token_hex(3)


def ensure_ids(spec: dict) -> dict:
    """به صفحه‌ها و بلوک‌های بدون `id` شناسه می‌دهد (پیش‌نویس‌های ویزارد قدیمی)؛ `spec` را درجا تغییر می‌دهد و برمی‌گرداند."""
    seen: set[str] = set()
    for p in spec.get("pages") or []:
        for b in p.get("blocks") or []:
            if not b.get("id") or b["id"] in seen:
                b["id"] = new_id()
            seen.add(b["id"])
    return spec


def empty(name: str = "") -> dict:
    return {"intro": {"summary": "", "icon": "chart"}, "tables": [], "pages": []}


def _page(spec: dict, key: str) -> dict:
    for p in spec.get("pages") or []:
        if p.get("key") == key:
            return p
    raise BlueprintError("صفحه پیدا نشد.")


def _find_block(spec: dict, bid: str) -> tuple[dict, int]:
    for p in spec.get("pages") or []:
        for i, b in enumerate(p.get("blocks") or []):
            if b.get("id") == bid:
                return p, i
    raise BlueprintError("بلوک پیدا نشد.")


def _clean(v: Any, depth: int = 0) -> Any:
    """مقدار JSON ساده‌ی بلوک (متن کوتاه‌شده، فهرست و دیکشنری ساده)."""
    if depth > 5:
        raise BlueprintError("ساختار بلوک بیش از حد تودرتو است.")
    if isinstance(v, str):
        return v[:BLOCK_STR_LIMIT]
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, list):
        return [_clean(x, depth + 1) for x in v[:60]]
    if isinstance(v, dict):
        return {str(k)[:40]: _clean(x, depth + 1) for k, x in list(v.items())[:40]}
    raise BlueprintError("مقدار نامعتبر در بلوک.")


def _block_in(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise BlueprintError("بلوک باید یک شیء باشد.")
    kind = raw.get("kind")
    if kind not in wizard.KINDS:
        raise BlueprintError("نوع بلوک نامعتبر است.")
    b = _clean(raw)
    b.pop("id", None)
    if b.get("width") not in (None, "") and b["width"] not in WIDTHS:
        raise BlueprintError("عرض بلوک نامعتبر است.")
    if not b.get("width"):
        b.pop("width", None)
    return b


def _page_fields(raw: dict) -> dict:
    out = {}
    for k in PAGE_FIELDS:
        if k not in raw:
            continue
        v = raw[k]
        if k == "params":
            if not isinstance(v, list) or len(v) > wizard.MAX_PARAMS:
                raise BlueprintError(f"حداکثر {wizard.MAX_PARAMS} فیلتر در هر صفحه.")
            v = _clean(v)
            if not all(isinstance(x, dict) for x in v):
                raise BlueprintError("هر فیلتر یک شیء است.")
            names = [x.get("name") for x in v]
            if len(set(names)) != len(names):
                raise BlueprintError("نام فیلترها باید یکتا باشد.")
            for x in v:
                try:
                    wizard.pagekit.parse_param(x)
                except wizard.pagekit.SpecError as exc:
                    raise BlueprintError(f"فیلتر «{x.get('label') or x.get('name')}»: {exc}") from exc
                if x["kind"] not in wizard.PARAM_BIND_KINDS:
                    raise BlueprintError("نوع فیلتر «انتخابی» یا «متن» است.")
        elif k == "refresh":
            if isinstance(v, bool) or not isinstance(v, int) or not (v == 0 or 5 <= v <= 3600):
                raise BlueprintError("تازه‌سازی صفر یا بین ۵ تا ۳۶۰۰ ثانیه است.")
        else:
            v = str(v).strip()
            if k == "title" and not (1 <= len(v) <= 80):
                raise BlueprintError("عنوان صفحه ۱ تا ۸۰ نویسه است.")
            if k == "subtitle":
                v = v[:240]
            if k == "group" and v not in GROUPS:
                raise BlueprintError("گروه منو نامعتبر است.")
            if k == "need" and v not in NEEDS:
                raise BlueprintError("سطح دسترسی نامعتبر است.")
            if k == "icon" and not re.fullmatch(r"[a-z0-9_-]{1,40}", v):
                raise BlueprintError("آیکون نامعتبر است.")
        out[k] = v
    return out


def _next_key(spec: dict) -> str:
    return wizard.next_page_key(spec)


def _insert(items: list, item: Any, at: Any) -> None:
    n = len(items)
    pos = n if at is None else max(0, min(int(at), n))
    items.insert(pos, item)


def apply(spec: dict, plugin_id: str, op: dict) -> dict:
    """یک عملیات ← نقشه‌ی تازه. `op["op"]` یکی از: meta.set، table.add|set|del، page.add|set|del|move، block.add|set|del|move|dup."""
    if not isinstance(op, dict) or not isinstance(op.get("op"), str):
        raise BlueprintError("عملیات نامعتبر است.")
    s = ensure_ids(copy.deepcopy(spec) if spec else empty())
    s.setdefault("intro", {})
    s.setdefault("tables", [])
    s.setdefault("pages", [])
    name = op["op"]
    fn = _OPS.get(name)
    if fn is None:
        raise BlueprintError(f"عملیات «{name}» شناخته‌شده نیست.")
    fn(s, plugin_id, op)
    return s


def apply_all(spec: dict, plugin_id: str, ops: list) -> dict:
    """دسته‌ی عملیات، همه یا هیچ (اگر یکی خطا دهد نقشه‌ی اصلی دست‌نخورده می‌ماند)."""
    if not isinstance(ops, list) or not ops:
        raise BlueprintError("فهرست عملیات خالی است.")
    if len(ops) > 60:
        raise BlueprintError("حداکثر ۶۰ عملیات در یک دسته.")
    s = spec
    for i, op in enumerate(ops, 1):
        try:
            s = apply(s, plugin_id, op)
        except BlueprintError as exc:
            raise BlueprintError(f"عملیات {i}: {exc}") from exc
    return s


# ---------------------------------------------------------------------- عملیات
def _meta_set(s, pid, op):
    intro = s["intro"]
    if "summary" in op:
        intro["summary"] = str(op["summary"]).strip()[:240]
    if "icon" in op:
        icon = str(op["icon"]).strip()
        if not re.fullmatch(r"[a-z0-9_-]{1,40}", icon):
            raise BlueprintError("آیکون نامعتبر است.")
        intro["icon"] = icon


def _table_in(pid: str, raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise BlueprintError("جدول باید یک شیء باشد.")
    t = _clean(raw)
    try:
        wizard.validate_tables(pid, [t])
    except wizard.WizardError as exc:
        raise BlueprintError(str(exc)) from exc
    return t


def _table_add(s, pid, op):
    t = _table_in(pid, op.get("table"))
    if any(x["name"] == t["name"] for x in s["tables"]):
        raise BlueprintError(f"جدول «{t['name']}» از قبل هست.")
    s["tables"].append(t)
    try:
        wizard.validate_tables(pid, s["tables"])
    except wizard.WizardError as exc:
        raise BlueprintError(str(exc)) from exc


def _table_set(s, pid, op):
    """جایگزینی کامل تعریف جدول (افزودن/حذف ستون = ارسال تعریف تازه). با `rename_from` نام هم عوض می‌شود و ارجاع بلوک‌ها همراه می‌رود."""
    t = _table_in(pid, op.get("table"))
    old = str(op.get("rename_from") or t["name"])
    for i, x in enumerate(s["tables"]):
        if x["name"] == old:
            if old != t["name"]:
                if any(y["name"] == t["name"] for y in s["tables"]):
                    raise BlueprintError(f"جدول «{t['name']}» از قبل هست.")
                for p in s["pages"]:
                    for b in p.get("blocks") or []:
                        if b.get("table") == old:
                            b["table"] = t["name"]
            s["tables"][i] = t
            return
    raise BlueprintError("جدول پیدا نشد.")


def _table_del(s, pid, op):
    name = str(op.get("name", ""))
    n = len(s["tables"])
    s["tables"] = [t for t in s["tables"] if t["name"] != name]
    if len(s["tables"]) == n:
        raise BlueprintError("جدول پیدا نشد.")


def _page_add(s, pid, op):
    if len(s["pages"]) >= MAX_PAGES:
        raise BlueprintError(f"حداکثر {MAX_PAGES} صفحه.")
    f = _page_fields({"icon": "chart", "group": "data", "need": "viewer", "refresh": 0, **{k: op[k] for k in PAGE_FIELDS if k in op}})
    if "title" not in f or not f["title"]:
        raise BlueprintError("عنوان صفحه را بنویسید.")
    page = {"key": _next_key(s), **f, "blocks": []}
    _insert(s["pages"], page, op.get("at"))
    for raw in op.get("blocks") or []:
        page["blocks"].append({**_block_in(raw), "id": new_id()})
    if len(page["blocks"]) > MAX_BLOCKS:
        raise BlueprintError(f"حداکثر {MAX_BLOCKS} بلوک در هر صفحه.")


def _page_set(s, pid, op):
    _page(s, str(op.get("key", ""))).update(_page_fields(op))


def _page_del(s, pid, op):
    key = str(op.get("key", ""))
    _page(s, key)
    s["pages"] = [p for p in s["pages"] if p["key"] != key]


def _page_move(s, pid, op):
    p = _page(s, str(op.get("key", "")))
    s["pages"].remove(p)
    _insert(s["pages"], p, op.get("to"))


def _block_add(s, pid, op):
    p = _page(s, str(op.get("page", "")))
    if len(p.setdefault("blocks", [])) >= MAX_BLOCKS:
        raise BlueprintError(f"حداکثر {MAX_BLOCKS} بلوک در هر صفحه.")
    b = {**_block_in(op.get("block")), "id": new_id()}
    _insert(p["blocks"], b, op.get("at"))


def _block_set(s, pid, op):
    """ادغام فیلدها در بلوک (مقدار null = برداشتن فیلد). `kind` عوض نمی‌شود، مگر صریح بیاید و معتبر باشد."""
    p, i = _find_block(s, str(op.get("id", "")))
    fields = op.get("fields")
    if not isinstance(fields, dict):
        raise BlueprintError("فیلدهای بلوک را بفرستید.")
    cur = dict(p["blocks"][i])
    for k, v in fields.items():
        if k == "id":
            continue
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = v
    new = _block_in({k: v for k, v in cur.items() if k != "id"})
    p["blocks"][i] = {**new, "id": cur["id"]}


def _block_del(s, pid, op):
    p, i = _find_block(s, str(op.get("id", "")))
    p["blocks"].pop(i)


def _block_move(s, pid, op):
    """جابه‌جایی در همان صفحه یا به صفحه‌ی دیگر (`page`)؛ `at` جایگاه (۰-پایه، خالی = انتها)."""
    src, i = _find_block(s, str(op.get("id", "")))
    dst = _page(s, str(op["page"])) if op.get("page") else src
    if dst is not src and len(dst.setdefault("blocks", [])) >= MAX_BLOCKS:
        raise BlueprintError(f"حداکثر {MAX_BLOCKS} بلوک در هر صفحه.")
    b = src["blocks"].pop(i)
    _insert(dst.setdefault("blocks", []), b, op.get("at"))


def _block_dup(s, pid, op):
    p, i = _find_block(s, str(op.get("id", "")))
    if len(p["blocks"]) >= MAX_BLOCKS:
        raise BlueprintError(f"حداکثر {MAX_BLOCKS} بلوک در هر صفحه.")
    b = copy.deepcopy(p["blocks"][i])
    b["id"] = new_id()
    if b.get("title"):
        b["title"] = (b["title"] + " (کپی)")[:80]
    p["blocks"].insert(i + 1, b)


def _code_get(s: dict, name: str) -> dict:
    h = (s.get("code") or {}).get(str(name))
    if h is None:
        raise BlueprintError("handler پیدا نشد.")
    return h


def _code_add(s, pid, op):
    """handler تازه از قالب (جدول و ستون از نقشه، اعتبارسنجی در wizard_code.build)."""
    name = str(op.get("name", "")).strip()
    code = s.setdefault("code", {})
    if not wizard_code.NAME_RE.fullmatch(name) or name in code:
        raise BlueprintError("نام handler نامعتبر یا تکراری است (حروف کوچک لاتین، رقم و _؛ ۲ تا ۳۱ نویسه).")
    if len(code) >= wizard_code.MAX_HANDLERS:
        raise BlueprintError(f"حداکثر {wizard_code.MAX_HANDLERS} handler.")
    params = op.get("params") if isinstance(op.get("params"), dict) else {}
    try:
        h = wizard_code.build(s, str(op.get("template", "")), {k: str(v) for k, v in params.items()})
    except wizard.WizardError as exc:
        raise BlueprintError(str(exc)) from exc
    h["cases"] = wizard_code.cases_from_toml(h.get("test", ""))
    code[name] = h


def _code_set(s, pid, op):
    h = _code_get(s, op.get("name"))
    if "source" in op:
        src = op["source"]
        if not isinstance(src, str) or len(src) > wizard_code.MAX_SOURCE:
            raise BlueprintError(f"کد باید متن و حداکثر {wizard_code.MAX_SOURCE:,} نویسه باشد.")
        h["source"] = src
    if "every" in op:
        e = op["every"]
        if isinstance(e, bool) or not isinstance(e, int) or not 5 <= e <= 1440:
            raise BlueprintError("فاصله‌ی هشدار بین ۵ و ۱۴۴۰ دقیقه است.")
        h["every"] = e
    if "cases" in op:
        if op["cases"] in (None, []):
            h["cases"], h["test"] = [], ""
        else:
            try:
                h["test"] = wizard_code.cases_toml(op["cases"])
                h["cases"] = wizard_code.normalize_cases(op["cases"])
            except wizard.WizardError as exc:
                raise BlueprintError(str(exc)) from exc


def _code_new(s, pid, op):
    """handler تازه با کد و آزمونِ داده‌شده (بدون قالب)؛ فقط ساختار اینجا سنجیده می‌شود، بررسی ایستا در `analyze` و runner است."""
    name = str(op.get("name", "")).strip()
    code = s.setdefault("code", {})
    if not wizard_code.NAME_RE.fullmatch(name) or name in code:
        raise BlueprintError("نام handler نامعتبر یا تکراری است (حروف کوچک لاتین، رقم و _؛ ۲ تا ۳۱ نویسه).")
    if len(code) >= wizard_code.MAX_HANDLERS:
        raise BlueprintError(f"حداکثر {wizard_code.MAX_HANDLERS} handler.")
    role = op.get("role")
    if role not in wizard_code.ROLES:
        raise BlueprintError("نقش handler نامعتبر است.")
    src = op.get("source")
    if not isinstance(src, str) or not src.strip() or len(src) > wizard_code.MAX_SOURCE:
        raise BlueprintError(f"کد لازم است (حداکثر {wizard_code.MAX_SOURCE:,} نویسه).")
    known = {t["name"] for t in s.get("tables") or []}
    tbls = [t for t in (op.get("tables") or []) if isinstance(t, str)]
    if any(t not in known for t in tbls):
        raise BlueprintError("جدول handler در نقشه نیست.")
    h = {"role": role, "source": src, "test": "", "every": 60 if role == "alert" else None, "tables": tbls, "cases": []}
    code[name] = h
    if "every" in op:
        _code_set(s, pid, {"name": name, "every": op["every"]})
    if op.get("cases"):
        _code_set(s, pid, {"name": name, "cases": op["cases"]})


def _code_del(s, pid, op):
    name = str(op.get("name", ""))
    _code_get(s, name)
    del s["code"][name]


def _listing_set(s, pid, op):
    """آگهی بازار: دسته، ویژگی‌ها (تا ۶ مورد) و توضیح کامل؛ عنوان و خلاصه از نام و توضیح کوتاه پلاگین می‌آید."""
    lst = s.setdefault("listing", {})
    if "category" in op:
        c = str(op["category"] or "")
        if c and c not in {x[0] for x in market.CATEGORIES}:
            raise BlueprintError("دسته‌ی آگهی نامعتبر است.")
        lst["category"] = c
    if "features" in op:
        f = op["features"]
        if not isinstance(f, list):
            raise BlueprintError("ویژگی‌ها فهرست متن است.")
        f = [str(x).strip() for x in f if str(x).strip()]
        if len(f) > market.MAX_FEATURES or any(len(x) > 80 for x in f):
            raise BlueprintError(f"حداکثر {market.MAX_FEATURES} ویژگی، هرکدام تا ۸۰ نویسه.")
        lst["features"] = f
    if "details" in op:
        d = str(op["details"] or "").strip()
        if len(d) > market.MAX_DETAILS:
            raise BlueprintError(f"توضیح کامل حداکثر {market.MAX_DETAILS} نویسه است.")
        lst["details"] = d


_OPS = {
    "listing.set": _listing_set,
    "code.add": _code_add, "code.new": _code_new, "code.set": _code_set, "code.del": _code_del,
    "meta.set": _meta_set, "table.add": _table_add, "table.set": _table_set, "table.del": _table_del,
    "page.add": _page_add, "page.set": _page_set, "page.del": _page_del, "page.move": _page_move,
    "block.add": _block_add, "block.set": _block_set, "block.del": _block_del, "block.move": _block_move, "block.dup": _block_dup,
}


# ---------------------------------------------------------------------- تحلیل
def analyze(spec: dict, plugin_id: str) -> dict:
    """ایرادهای نقشه: {issues: [{scope, page, block, message}]، ok}. `scope` ∈ meta|table|page|block.
    ok = قابل‌ساخت (compile_pages بدون خطا) و بدون ایراد."""
    issues: list[dict] = []

    def add(scope, message, page="", block=""):
        issues.append({"scope": scope, "page": page, "block": block, "message": message})

    try:
        wizard.validate_tables(plugin_id, spec.get("tables") or [])
    except wizard.WizardError as exc:
        add("table", str(exc))
    for p in spec.get("pages") or []:
        if not p.get("blocks"):
            add("page", "صفحه دست‌کم یک بلوک نمایشی لازم دارد.", p["key"])
        for b in p.get("blocks") or []:
            try:
                wizard.check_block(spec, b, p)
            except wizard.WizardError as exc:
                add("block", str(exc), p["key"], b.get("id", ""))
    for name, h in (spec.get("code") or {}).items():
        try:
            wizard_code.check_source(h.get("source", ""), name)
        except wizard.WizardError as exc:
            issues.append({"scope": "code", "page": "", "block": "", "handler": name, "message": str(exc)})
        text = h.get("test", "")
        if not (text or "").strip():
            issues.append({"scope": "code", "page": "", "block": "", "handler": name, "message": "آزمون ندارد؛ برای انتشار هر handler دست‌کم یک مورد آزمون لازم است."})
        else:
            from . import pkgtest

            try:
                pkgtest.parse(text, name)
            except pkgtest.TestSpecError as exc:
                issues.append({"scope": "code", "page": "", "block": "", "handler": name, "message": str(exc)})
    if not (spec.get("pages") or []):
        add("meta", "دست‌کم یک صفحه لازم است.")
    if not issues:
        try:
            wizard.compile_pages(plugin_id, spec)
        except wizard.WizardError as exc:
            add("meta", str(exc))
    return {"issues": issues, "ok": not issues}
