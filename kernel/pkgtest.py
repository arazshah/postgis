"""آزمون خودکار بسته‌ی سطح ۲ (مرحله‌ی ۴ ADR-0002): هر handler یک فایل `tests/<handler>.toml` با چند مورد دارد.

آزمون **اعلانی** است (نه کد دوم): ورودی نمونه، فایل نمونه، پاسخ ساختگی `ctx.sql` و انتظار. اجرا همان مسیر مدل‌آگاه runner است
(`client.run_files`)، پس در حالت `off` اجرا نمی‌شود؛ پاسخ ساختگی داخل خود درخواست می‌رود و هیچ اتصال پایگاه داده‌ای لازم نیست.

```toml
[[cases]]
name = "دو ردیف"
params = {n = 1}
file = "a,1\\nb,2"                 # فقط handler ورود
[[cases.sql]]
match = "select count"              # زیررشته‌ی پرس‌وجو (بدون حساسیت به حروف)
columns = ["n"]
rows = [[2]]
[cases.expect]
rows_count = 2                      # | equals = {...} | error_contains = "..." | text_contains = "..." | alerts_count = 1
```
ورود/خروج مثل کاربرد واقعی اعتبارسنجی می‌شود (`pluginio`)؛ هیچ چیز نوشته نمی‌شود.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field

from . import pluginio

MAX_CASES_PER_HANDLER, MAX_CASES = 10, 30
EXPECT_KEYS = ("equals", "rows_count", "error_contains", "text_contains", "alerts_count")


class TestSpecError(ValueError):
    __test__ = False


@dataclass(frozen=True)
class Case:
    name: str
    params: dict = field(default_factory=dict)
    file: bytes | None = None
    sql: tuple = ()
    expect: dict = field(default_factory=dict)


def parse(text: str, handler: str) -> list[Case]:
    try:
        d = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise TestSpecError(f"tests/{handler}.toml خوانده نشد: {exc}") from exc
    raw = d.get("cases") or []
    if not isinstance(raw, list) or not raw:
        raise TestSpecError(f"tests/{handler}.toml دست‌کم یک [[cases]] لازم دارد.")
    if len(raw) > MAX_CASES_PER_HANDLER:
        raise TestSpecError(f"حداکثر {MAX_CASES_PER_HANDLER} مورد برای هر handler.")
    out = []
    for i, c in enumerate(raw, 1):
        if not isinstance(c, dict):
            raise TestSpecError(f"مورد {i} نامعتبر است.")
        name = str(c.get("name") or f"مورد {i}")[:80]
        params = c.get("params", {})
        sql = c.get("sql", [])
        expect = c.get("expect", {})
        file = c.get("file")
        if not isinstance(params, dict) or not isinstance(expect, dict) or not isinstance(sql, list) or (file is not None and not isinstance(file, str)):
            raise TestSpecError(f"«{name}»: params/expect باید جدول، sql فهرست جدول و file رشته باشد.")
        if any(not isinstance(m, dict) or "match" not in m for m in sql):
            raise TestSpecError(f"«{name}»: هر sql باید match داشته باشد.")
        bad = set(expect) - set(EXPECT_KEYS)
        if bad:
            raise TestSpecError(f"«{name}»: کلید انتظار ناشناخته: {'، '.join(sorted(bad))} (مجاز: {'، '.join(EXPECT_KEYS)}).")
        if not expect:
            raise TestSpecError(f"«{name}»: expect خالی است؛ دست‌کم یک انتظار بنویسید.")
        out.append(Case(name, params, file.encode() if file is not None else None, tuple(sql), expect))
    return out


def roles_of(pages) -> dict:
    """نقش هر handler در صفحه‌ها: ("import"، spec) | ("export"، spec) | ("block"، None)."""
    out: dict = {}
    for pg in pages:
        for b in pg.blocks:
            if b.handler:
                out.setdefault(b.handler, ("block", None))
        for im in pg.imports:
            out[im.handler] = ("import", im)
        for ex in pg.exports:
            out[ex.handler] = ("export", ex)
        for ig in pg.ingests:
            if ig.handler:
                out[ig.handler] = ("ingest", ig)
    return out


def _check_ingest(spec, out) -> int:
    """خروجی handler دریافت: {rows: [{فیلد: مقدار}]} و هر ردیف باید از اعتبارسنجی فیلدهای هسته بگذرد؛ شمار ردیف."""
    from . import pagekit

    rows = out.get("rows") if isinstance(out, dict) else None
    if not isinstance(rows, list) or not rows:
        raise pluginio.PluginIOError("handler باید {rows: [{...}]} با دست‌کم یک ردیف برگرداند.")
    if len(rows) > spec.max_rows:
        raise pluginio.PluginIOError(f"بیش از سقف {spec.max_rows} ردیف.")
    for i, r in enumerate(rows, 1):
        try:
            pagekit.read_ingest_row(spec, r)
        except ValueError as exc:
            raise pluginio.PluginIOError(f"ردیف {i}: {exc}") from exc
    return len(rows)


def run_case(handler: str, source: str, role: str, spec, case: Case) -> str:
    """یک مورد؛ "" اگر گذشت، وگرنه پیام فارسی کوتاه."""
    from .runner import client

    try:
        out = client.run_files({f"code/{handler}.py": source}, handler, case.params, None, 0, file=case.file,
                               io=role in ("import", "export", "ingest"), allow_no_ws=True, mock_sql=list(case.sql), plugin="pkgtest")
    except client.HandlerFailed as exc:
        want = case.expect.get("error_contains")
        return "" if want and str(want) in str(exc) else f"اجرا شکست خورد: {exc}"
    except client.RunnerError as exc:
        raise TestSpecError(str(exc)) from exc  # زیرساخت (مثلاً runner خاموش): آزمون نامعتبر نیست، اجرا ممکن نیست
    if "error_contains" in case.expect:
        return "انتظار خطا بود ولی اجرا موفق شد."
    try:
        if role == "import":
            t = pluginio.normalize_import("test_table", out)
            rows = len(t.rows)
        elif role == "ingest":
            rows = _check_ingest(spec, out)
        elif role == "export":
            _name, body, _ct = pluginio.normalize_export(out, spec.format)
            rows, text = None, body.decode("utf-8")
            if "text_contains" in case.expect and str(case.expect["text_contains"]) not in text:
                return f"متن خروجی «{case.expect['text_contains']}» را ندارد."
        else:
            rows = len(out.get("rows", [])) if isinstance(out, dict) else None
    except pluginio.PluginIOError as exc:
        return f"خروجی معتبر نیست: {exc}"
    if "rows_count" in case.expect and rows != case.expect["rows_count"]:
        return f"تعداد ردیف {rows} است، انتظار {case.expect['rows_count']} بود."
    if "equals" in case.expect and out != case.expect["equals"]:
        return "خروجی با equals برابر نیست."
    if "alerts_count" in case.expect:
        n = len(out.get("alerts", [])) if isinstance(out, dict) else -1
        if n != case.expect["alerts_count"]:
            return f"تعداد هشدار {n} است، انتظار {case.expect['alerts_count']} بود."
    return ""


def run_all(code: dict[str, str], tests: dict[str, list[Case]], roles: dict) -> list[dict]:
    """همه‌ی موردها؛ [{handler, case, ok, message}]. TestSpecError یعنی اجرا ممکن نیست (مثلاً runner خاموش)."""
    results = []
    for handler, cases in sorted(tests.items()):
        role, spec = roles.get(handler, ("block", None))
        for c in cases:
            msg = run_case(handler, code[handler], role, spec, c)
            results.append({"handler": handler, "case": c.name, "ok": not msg, "message": msg})
    return results
