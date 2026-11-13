"""درون‌ریز پلاگین‌های قبلی به استودیوی دیداری (docs/adr/0010، مرحله‌ی ۹): صفحه‌های TOML، کد و آزمون ← نقشه‌ی پلاگین.

- ورودی: پیش‌نویس استودیوی TOML قدیمی (`from_draft`) یا بسته‌ی یک نسخه‌ی منتشرشده/نصب‌شده (`from_files`).
- هر ساخت کیت به بلوک هم‌نوعش می‌رود (فرم، دریافت، ویرایش ردیف، منبع، گزارش، ورود/خروج)؛ بلوک‌های دارای `sql` به «SQL پیشرفته»
  (بی‌اتلاف) و تفاوت فیلدها با ستون جدول در `overrides`. کلیدها (key) حفظ می‌شوند تا نشانی‌ها، توکن‌های دریافت و وضعیت منبع‌ها نشکنند.
- **راستی‌آزمایی بی‌اتلاف:** نقشه دوباره کامپایل و `pagekit.Page` حاصل با اصلی مقایسه می‌شود. هر ساختی که یکسان درنیاید به **بلوک خام**
  (همان مشخصات TOML بی‌تغییر، فقط‌خواندنی در استودیو، با همان بررسی کیت) می‌رود تا هیچ پلاگینی بازنشدنی نباشد؛ تفاوت‌های باقی‌مانده
  (فیلتر، جدول‌ها، فیلدهای صفحه) در گزارش می‌آید.
- فقط می‌خواند و می‌سازد؛ چیزی منتشر یا اجرا نمی‌شود. بلوک خام را فقط همین ماژول می‌سازد (عملیات مرورگر `raw` را رد می‌کند).
"""
from __future__ import annotations

import copy
import dataclasses
import itertools
import tomllib
from dataclasses import dataclass

from . import blueprint, pagekit, pkg, wizard, wizard_code

DEFAULTS = {"form": {"submit": "ثبت", "hint": "", "success": "ثبت شد."}, "import": {"hint": "", "submit": "ورود فایل", "success": "جدول ساخته شد."},
            "export": {"hint": "", "submit": "دریافت خروجی"}}
PAGE_PARTS = (("forms", "forms"), ("ingests", "ingest"), ("records", "records"), ("sources", "sources"), ("imports", "imports"), ("exports", "exports"), ("reports", "reports"))
ROLE_PRIORITY = ("importer", "exporter", "ingest", "alert", "block")


class ImportFailed(ValueError):
    """پیام فارسی: پلاگین قابل‌ورود نیست."""


@dataclass
class Imported:
    plugin_id: str
    name: str
    version: str
    readme: str
    kind: str
    requires: str
    spec: dict
    report: dict


# ---------------------------------------------------------------------- ورودی‌ها
def _toml(text: str, what: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ImportFailed(f"{what} خوانده نشد: {exc}") from exc


def from_files(files: dict[str, bytes]) -> Imported:
    """از فایل‌های بسته (`pkg.read_archive`)."""
    try:
        m = pkg._manifest(files)
    except pkg.PackageError as exc:
        raise ImportFailed(str(exc)) from exc
    pages = {n[6:-5]: _toml(b.decode("utf-8", "replace"), n) for n, b in sorted(files.items()) if n.startswith("pages/") and n.endswith(".toml")}
    code = {n[5:-3]: b.decode("utf-8", "replace") for n, b in files.items() if n.startswith("code/") and n.endswith(".py")}
    tests = {n[6:-5]: b.decode("utf-8", "replace") for n, b in files.items() if n.startswith("tests/") and n.endswith(".toml")}
    alerts = {a["handler"]: int(a["every_minutes"]) for a in ((m.get("contributes") or {}).get("alerts") or []) if isinstance(a, dict) and "handler" in a and "every_minutes" in a}
    readme = files.get("README.md", b"").decode("utf-8", "replace")
    return build(str(m["id"]), str(m["name"]), pages, code, tests, alerts, summary=str(m.get("description", "")), readme=readme,
                 version=str(m.get("version", "1.0.0")), kind=str(m.get("kind", "custom")), requires=",".join(m.get("requires") or []))


def from_draft(draft) -> Imported:
    """از پیش‌نویس استودیوی TOML قدیمی (`PluginDraft.pages|code|tests|alerts`)."""
    pages = {k: _toml(t, f"pages/{k}.toml") for k, t in sorted((draft.pages or {}).items())}
    return build(draft.plugin_id, draft.name, pages, dict(draft.code or {}), dict(draft.tests or {}), {k: int(v) for k, v in (draft.alerts or {}).items()},
                 summary=str(((draft.wizard or {}).get("intro") or {}).get("summary", "")), readme=draft.readme or "", version=draft.version,
                 kind=draft.kind, requires=draft.requires)


# ---------------------------------------------------------------------- تبدیل
def _field_dict(f) -> dict:
    return {"kind": f.kind, "label": f.label, "required": bool(f.required), "choices": [list(c) for c in f.choices], "max": f.max, "min": f.min, "geom": f.geom}


def _norm(d: dict, k):
    v = d.get(k)
    if k in ("choices",):
        return [list(x) for x in v or []]
    if k in ("geom",):
        return v or ""
    if k == "required":
        return bool(v)
    return v


def _overrides(fields, table: dict) -> dict:
    """تفاوت فیلدهای اعلام‌شده با فیلدی که از ستون جدول ساخته می‌شود؛ WizardError اگر ستون نیست یا نوعش پشتیبانی نمی‌شود."""
    cols = wizard.columns_of(table)
    out = {}
    for f in fields:
        col = cols.get(f.name)
        if col is None:
            raise wizard.WizardError(f"ستون «{f.name}» در جدول نیست.")
        gen, orig = wizard._field_for(col), _field_dict(f)
        diff = {k: orig[k] for k in wizard.OVERRIDE_KEYS if _norm(orig, k) != _norm(gen, k)}
        if diff:
            out[f.name] = {k: ([list(x) for x in v] if k == "choices" else v) for k, v in diff.items()}
    return out


def _with_defaults(block: dict, obj, kind: str) -> dict:
    for k, dflt in DEFAULTS.get(kind, {}).items():
        v = getattr(obj, k, dflt)
        if v != dflt:
            block[k] = v
    return block


def _form_block(tables, f, key):
    t = tables.get(f.table)
    if t is None:
        return None
    b = {"kind": "form", "key": key, "title": f.title, "table": f.table, "fields": [x.name for x in f.fields]}
    ov = _overrides(f.fields, t)
    if ov:
        b["overrides"] = ov
    return _with_defaults(b, f, "form")


def _ingest_block(tables, i, key):
    t = tables.get(i.table)
    if t is None:
        return None
    b = {"kind": "ingest", "key": key, "title": i.title, "table": i.table, "fields": [x.name for x in i.fields], "max_rows": i.max_rows, "rate": i.rate}
    if i.handler:
        b["handler"] = i.handler
    if i.hint:
        b["hint"] = i.hint
    ov = _overrides(i.fields, t)
    if ov:
        b["overrides"] = ov
    return b


def _records_block(tables, r, key):
    t = tables.get(r.table)
    if t is None:
        return None
    b = {"kind": "records", "key": key, "title": r.title, "table": r.table, "fields": [x.name for x in r.fields], "columns": list(r.columns),
         "can_delete": r.can_delete, "limit": r.limit}
    if r.hint:
        b["hint"] = r.hint
    ov = _overrides(r.fields, t)
    if ov:
        b["overrides"] = ov
    return b


def _source_block(tables, s, key):
    t = tables.get(s.table)
    if t is None:
        return None
    paths, consts, optional = dict(s.paths), dict(s.consts), set(s.optional)
    rows = []
    for f in s.fields:
        row: dict = {"column": f.name}
        if f.name in consts:
            row["input"] = consts[f.name]
        else:
            row["path"] = paths.get(f.name, f.name)
        if f.name in optional:
            row["optional"] = True
        rows.append(row)
    b = {"kind": "source", "key": key, "title": s.title, "table": s.table, "url": s.url, "layout": s.layout, "every_minutes": s.every_minutes,
         "since_days": s.since_days, "query": [list(q) for q in s.query], "map": rows}
    for k in ("rows_path", "cursor", "hint", "secret_header", "secret_param"):
        if getattr(s, k):
            b[k] = getattr(s, k)
    if s.mode != "append":
        b["mode"] = s.mode
    if s.inputs:
        b["inputs"] = [{k: ([list(c) for c in v] if k == "choices" else v) for k, v in dataclasses.asdict(i).items() if v not in (None, "", ()) or k == "required"} for i in s.inputs]
    ov = _overrides(s.fields, t)
    if ov:
        b["overrides"] = ov
    return b


def _display_block(b, new_id):
    """بلوک نمایشی ← بلوک نقشه (SQL پیشرفته، خروجی کد یا متن)؛ بی‌اتلاف."""
    dflt_w = "third" if b.kind == "kpi" else "full"
    out: dict = {"id": new_id(), "title": b.title}
    if b.kind == "text":
        out.update(kind="text", text=b.text)
    elif b.handler:
        out.update(kind="handler", display=b.kind, handler=b.handler)
        if b.unit:
            out["unit"] = b.unit
    else:
        out.update(kind="sql", display=b.kind, sql=b.sql)
        if b.unit:
            out["unit"] = b.unit
        if b.hint:
            out["hint"] = b.hint
        if b.columns:
            out["columns"] = [list(c) for c in b.columns]
    if b.width != dflt_w:
        out["width"] = b.width
    return out


def _raw(part: str, item: dict, title: str, key: str, new_id) -> dict:
    return {"kind": "raw", "id": new_id(), "part": part, "item": copy.deepcopy(item), "title": title, "key": key}


def _compile(spec: dict, plugin_id: str, spage: dict):
    built = wizard.build_page(spec, plugin_id, spage)
    return pagekit.parse_page(plugin_id, tomllib.loads(wizard.toml_dumps(built)))


def _mismatch(a, b) -> tuple[set, set, list]:
    """(ساخت‌های ناهمسان (part، key)، شاخص بلوک‌های نمایشی ناهمسان، یادداشت‌های غیرقابل‌جایگزینی)."""
    parts, blocks, notes = set(), set(), []
    for i, (x, y) in enumerate(itertools.zip_longest(a.blocks, b.blocks)):
        if x != y:
            blocks.add(i)
    for attr, part in PAGE_PARTS:
        new = {x.key: x for x in getattr(b, attr)}
        for x in getattr(a, attr):
            if new.get(x.key) != x:
                parts.add((part, x.key))
        for k in set(new) - {x.key for x in getattr(a, attr)}:
            notes.append(f"صفحه‌ی «{a.title}»: {part} «{k}» اضافه ساخته شد")
    for f in ("title", "subtitle", "icon", "group", "need", "order", "refresh", "params"):
        if getattr(a, f) != getattr(b, f):
            notes.append(f"صفحه‌ی «{a.title}»: «{f}» با اصل یکی نیست")
    if {t.name: t for t in a.tables} != {t.name: t for t in b.tables}:
        notes.append(f"صفحه‌ی «{a.title}»: جدول‌های اعلام‌شده با اصل یکی نیست")
    return parts, blocks, notes


def build(plugin_id: str, name: str, pages: dict[str, dict], code: dict[str, str], tests: dict[str, str], alerts: dict[str, int], *,
          summary: str = "", readme: str = "", version: str = "1.0.0", kind: str = "custom", requires: str = "") -> Imported:
    """صفحه‌ها (dict از TOML)، کد، آزمون و هشدارها ← Imported با نقشه و گزارش راستی‌آزمایی."""
    if not pages:
        raise ImportFailed("پلاگین صفحه‌ای ندارد؛ چیزی برای ورود نیست.")
    orig: dict[str, pagekit.Page] = {}
    for key, d in pages.items():
        try:
            orig[key] = pagekit.parse_page(plugin_id, d)
        except pagekit.SpecError as exc:
            raise ImportFailed(f"صفحه‌ی «{key}» از بررسی کیت نمی‌گذرد: {exc}") from exc
    order = sorted(orig, key=lambda k: (orig[k].order, k))
    notes: list[str] = []
    # ---- نقش handlerها از روی کاربردشان
    use: dict[str, set] = {}
    for pg in orig.values():
        for b in pg.blocks:
            if b.handler:
                use.setdefault(b.handler, set()).add("block")
        for i in pg.imports:
            use.setdefault(i.handler, set()).add("importer")
        for e in pg.exports:
            use.setdefault(e.handler, set()).add("exporter")
        for g in pg.ingests:
            if g.handler:
                use.setdefault(g.handler, set()).add("ingest")
    spec_code: dict[str, dict] = {}
    for h, src in code.items():
        roles = set(use.get(h, set())) | ({"alert"} if h in alerts else set())
        role = next((r for r in ROLE_PRIORITY if r in roles), "block")
        if len(roles) > 1:
            notes.append(f"کد «{h}» هم‌زمان در نقش‌های {'، '.join(sorted(roles))} است؛ نقش «{role}» انتخاب شد")
        text = tests.get(h, "")
        spec_code[h] = {"role": role, "source": src, "test": text, "every": alerts.get(h) if role == "alert" else None, "tables": [],
                        "cases": wizard_code.cases_from_toml(text) if text.strip() else []}
    # ---- جدول‌ها (اجتماع صفحه‌ها؛ نخستین تعریف)
    tables: dict[str, dict] = {}
    for key in order:
        for t in pages[key].get("tables") or []:
            tables.setdefault(t["name"], copy.deepcopy(t))
    spec: dict = {"intro": {"summary": summary[:240], "icon": orig[order[0]].icon or "chart"}, "tables": list(tables.values()), "pages": [], "code": spec_code}
    ids = iter(blueprint.new_id() for _ in itertools.count())
    seen: set[str] = set()

    def new_id() -> str:
        while True:
            i = next(ids)
            if i not in seen:
                seen.add(i)
                return i

    raw_report: list[dict] = []
    for key in order:
        d, pg = pages[key], orig[key]
        sp: dict = {"key": key, "title": pg.title, "subtitle": pg.subtitle, "icon": pg.icon, "group": pg.group, "need": pg.need, "order": pg.order,
                    "tables": [t.name for t in pg.tables], "blocks": []}
        if pg.refresh:
            sp["refresh"] = pg.refresh
        if d.get("params"):
            sp["params"] = copy.deepcopy(d["params"])
        disp = [_display_block(b, new_id) for b in pg.blocks]
        items = [(("blocks", i), disp[i], d["blocks"][i], b.title, "") for i, b in enumerate(pg.blocks)]
        conv = {"forms": _form_block, "ingest": _ingest_block, "records": _records_block, "sources": _source_block}
        extra = []
        for attr, part in PAGE_PARTS:
            for i, obj in enumerate(getattr(pg, attr)):
                od = (d.get(part) or [])[i]
                block = None
                try:
                    if part in conv:
                        block = conv[part](tables, obj, obj.key)
                    elif part == "imports":
                        block = _with_defaults({"kind": "import", "key": obj.key, "title": obj.title, "handler": obj.handler, "extensions": list(obj.extensions)}, obj, "import")
                    elif part == "exports":
                        block = _with_defaults({"kind": "export", "key": obj.key, "title": obj.title, "handler": obj.handler, "format": obj.format}, obj, "export")
                    elif part == "reports":
                        if all(1 <= n <= len(disp) for n in obj.blocks):
                            block = {"kind": "report", "key": obj.key, "title": obj.title, "blocks": [disp[n - 1]["id"] for n in obj.blocks], "landscape": obj.landscape,
                                     "button": obj.button, **({"subtitle": obj.subtitle} if obj.subtitle else {})}
                except wizard.WizardError:
                    block = None
                if block is not None:
                    block["id"] = new_id()
                extra.append(((part, obj.key), block, od, obj.title, obj.key))
        items += extra
        entries = [{"ref": ref, "block": blk, "orig": od, "title": t, "key": k} for ref, blk, od, t, k in items]

        # آزمودن و جایگزینی ساخت‌های ناهمسان با بلوک خام (حداکثر ۴ دور)
        failed = False
        for _ in range(4):
            for e in entries:
                if e["block"] is None and e.get("_raw") is None:
                    e["_raw"] = _raw(e["ref"][0], e["orig"], e["title"], e["key"], new_id)
            sp["blocks"] = [e["block"] if e["block"] is not None else e["_raw"] for e in entries]
            try:
                new = _compile(spec, plugin_id, sp)
            except (wizard.WizardError, pagekit.SpecError) as exc:
                if failed:
                    break  # همه‌ی بلوک‌ها خام‌اند و باز هم نمی‌شود (مثلاً مشکل جدول‌ها)؛ گزارش می‌شود
                failed = True
                for e in entries:
                    e["block"] = None
                notes.append(f"صفحه‌ی «{pg.title}»: بازسازی ساخت‌یافته ممکن نشد ({str(exc)[:120]}) و بلوک‌ها خام ماندند")
                continue
            parts, blocks, page_notes = _mismatch(pg, new)
            swap = [e for e in entries if (e["ref"][0] != "blocks" and e["ref"] in parts) or (e["ref"][0] == "blocks" and e["ref"][1] in blocks)]
            if not swap:
                notes += page_notes
                break
            for e in swap:
                e["block"] = None
        sp["blocks"] = [e["block"] if e["block"] is not None else e["_raw"] for e in entries]
        for e in entries:
            if e["block"] is None:
                raw_report.append({"page": pg.title, "part": e["ref"][0], "title": e["title"], "key": e["key"]})
        spec["pages"].append(sp)

    # ---- راستی‌آزمایی نهایی روی کل نقشه (همان مسیر انتشار)
    errors: list[str] = []
    try:
        wizard.validate_tables(plugin_id, spec["tables"])
        wizard_code.validate_code(spec)
        compiled = wizard.compile_pages(plugin_id, spec)
        for key in order:
            _p, _b, page_notes = _mismatch(orig[key], pagekit.parse_page(plugin_id, tomllib.loads(compiled[key])))
            notes += [n for n in page_notes if n not in notes]
    except wizard.WizardError as exc:
        errors.append(str(exc))
    report = {"lossless": not notes and not errors, "raw": raw_report, "notes": notes, "errors": errors,
              "stats": {"pages": len(spec["pages"]), "blocks": sum(len(p["blocks"]) for p in spec["pages"]), "tables": len(spec["tables"]), "handlers": len(spec_code)}}
    return Imported(plugin_id, name, version, readme, kind, requires, blueprint.ensure_ids(spec), report)
