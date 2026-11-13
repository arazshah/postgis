"""کد سطح ۲ در ویزارد (docs/adr/0008، مرحله‌ی ۴): قالب‌های handler برای GIS/سنجش‌ازدور، ساخت امن از روی جدول‌های ویزارد و بررسی ایستا.

مدیر قالب را انتخاب می‌کند و جدول/ستون‌ها را از فهرست جدول‌های همان ویزارد برمی‌گزیند؛ این ماژول جانشین‌های `@TABLE@` و … را فقط با
نام‌های اعتبارسنجی‌شده (الگوی شناسه + وجود در مشخصات) و عدد اعتبارسنجی‌شده پر می‌کند، پس متن آزاد وارد SQL قالب نمی‌شود.
کد خروجی در جعبه‌ی `plugin-runner` اجرا می‌شود (فقط کتابخانه‌ی استاندارد و `geo`) و هر قالب آزمون اعلانی خودش را دارد.
بدون وابستگی به جنگو.
"""
from __future__ import annotations

import re
import tomllib

from .runner import scan
from .wizard import IDENT_RE, WizardError, _key, _val, columns_of, table_map

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
ROLES = ("block", "importer", "exporter", "ingest", "alert")
ROLE_LABEL = {"block": "بلوک صفحه", "importer": "ورود فایل", "exporter": "خروجی فایل", "ingest": "تبدیل داده‌ی دریافتی", "alert": "هشدار دوره‌ای"}
MAX_HANDLERS, MAX_SOURCE = 8, 20_000
NUMERIC = ("integer", "bigint", "double")
# پارامتر قالب ← (برچسب، نوع‌های مجاز ستون یا None برای هر ستون)
COLS = {"num": ("ستون عددی", NUMERIC), "nir": ("ستون NIR", NUMERIC), "red": ("ستون Red", NUMERIC), "lat": ("ستون عرض", ("double",)),
        "lon": ("ستون طول", ("double",)), "time": ("ستون زمان/تاریخ", ("timestamptz", "date")), "tmin": ("ستون کمینه‌ی دما", NUMERIC),
        "tmax": ("ستون بیشینه‌ی دما", NUMERIC)}
NUMS = {"latv": ("عرض جغرافیایی ایستگاه (درجه)", -90.0, 90.0), "threshold": ("آستانه‌ی هشدار", -1e9, 1e9)}

BLOCK_TEST = '''[[cases]]
name = "نمونه"
[[cases.sql]]
match = "select"
columns = [{cols}]
rows = {rows}
[cases.expect]
rows_count = {n}
'''

TEMPLATES: dict[str, dict] = {
    "block_stats": {
        "role": "block", "title": "آمار یک ستون عددی", "hint": "تعداد، کمینه، بیشینه، میانگین، میانه و انحراف معیار", "needs": ["table", "num"],
        "source": '''import geo


def handle(ctx, params):
    r = ctx.sql('select "@NUM@" from "@TABLE@" where "@NUM@" is not null limit 100000')
    s = geo.stats([row[0] for row in r["rows"]])
    names = [("تعداد", "count"), ("کمینه", "min"), ("بیشینه", "max"), ("میانگین", "mean"), ("میانه", "median"), ("انحراف معیار", "stdev")]
    return {"columns": ["شاخص", "مقدار"], "rows": [[label, s[key]] for label, key in names]}
''',
        "test": BLOCK_TEST.format(cols='"v"', rows="[[1.0], [2.0], [3.0]]", n=6)},
    "block_ndvi_classes": {
        "role": "block", "title": "طبقه‌بندی NDVI (سنجش‌ازدور)", "hint": "از باندهای NIR و Red شاخص NDVI می‌سازد و پیکسل‌ها را در ۵ طبقه می‌شمارد (برای بلوک نمودار میله‌ای)",
        "needs": ["table", "nir", "red"],
        "source": '''import geo

LABELS = ["آب یا ابر", "خاک لخت", "پوشش کم", "پوشش متوسط", "پوشش انبوه"]
BREAKS = [0.0, 0.2, 0.4, 0.6]


def handle(ctx, params):
    r = ctx.sql('select "@NIR@", "@RED@" from "@TABLE@" where "@NIR@" is not null and "@RED@" is not null limit 100000')
    counts = {label: 0 for label in LABELS}
    for nir, red in r["rows"]:
        try:
            counts[geo.classify(geo.ndvi(nir, red), BREAKS, LABELS)] += 1
        except ValueError:
            pass  # NIR + Red = 0
    return {"columns": ["label", "value"], "rows": [[k, v] for k, v in counts.items()]}
''',
        "test": BLOCK_TEST.format(cols='"nir", "red"', rows="[[0.5, 0.1], [0.3, 0.25], [0.1, 0.3], [0.0, 0.0]]", n=5)},
    "block_et0_gdd": {
        "role": "block", "title": "تبخیر-تعرق و درجه‌روز رشد (کشاورزی و آب)", "hint": "از دمای کمینه/بیشینه‌ی روزانه، ET0 (هارگریوز) و GDD تجمعی ۳۰ روز اخیر", "needs": ["table", "time", "tmin", "tmax"],
        "nums": ["latv"],
        "source": '''import geo

LAT = @LATV@


def handle(ctx, params):
    r = ctx.sql('select "@TIME@"::date, "@TMIN@", "@TMAX@" from "@TABLE@" order by 1 desc limit 30')
    rows, total = [], 0.0
    for day, tmin, tmax in reversed(r["rows"]):
        d = str(day)
        doy = geo.day_of_year(int(d[0:4]), int(d[5:7]), int(d[8:10]))
        total += geo.gdd(tmin, tmax)
        rows.append([d[:10], round(geo.et0_hargreaves(tmin, tmax, LAT, doy), 2), round(total, 1)])
    return {"columns": ["تاریخ", "تبخیر-تعرق مرجع (mm)", "GDD تجمعی"], "rows": rows}
''',
        "test": BLOCK_TEST.format(cols='"d", "tmin", "tmax"', rows='[["2024-07-01", 20, 38], ["2024-07-02", 21, 39]]', n=2)},
    "importer_csv_points": {
        "role": "importer", "title": "ورود فایل CSV نقطه‌ها", "hint": "ستون‌ها: نام، عرض، طول و (اختیاری) مقدار؛ جدول تازه با ستون مکانی", "needs": [],
        "source": '''def handle(ctx, params):
    rows = []
    for n, line in enumerate(ctx.file().decode("utf-8-sig").splitlines()):
        p = [x.strip() for x in line.split(",")]
        if len(p) < 3 or not p[0]:
            continue
        try:
            lat, lon = float(p[1]), float(p[2])
        except ValueError:
            if n == 0:
                continue  # سطر عنوان
            raise ValueError(f"سطر {n + 1}: عرض یا طول عدد نیست.")
        rows.append([p[0], lat, lon, float(p[3]) if len(p) > 3 and p[3] else None])
    return {"columns": [{"name": "name", "type": "text"}, {"name": "lat", "type": "double"}, {"name": "lon", "type": "double"},
                        {"name": "value", "type": "double"}],
            "rows": rows, "geometry": {"lat": "lat", "lon": "lon"}}
''',
        "test": '''[[cases]]
name = "عنوان و دو نقطه"
file = "name,lat,lon,value\\nA,35.7,51.4,3\\nB,36,52,"
[cases.expect]
rows_count = 2

[[cases]]
name = "عرض نامعتبر"
file = "name,lat,lon\\nA,x,51.4"
[cases.expect]
error_contains = "عرض"
'''},
    "importer_geojson": {
        "role": "importer", "title": "ورود فایل GeoJSON نقطه‌ها", "hint": "نقطه‌ها (و MultiPoint) با ویژگی name؛ جدول تازه با ستون مکانی", "needs": [],
        "source": '''import geo


def handle(ctx, params):
    pts = geo.point_features(ctx.file().decode("utf-8-sig"))
    rows = [[p["lat"], p["lon"], str(p["properties"].get("name", ""))[:100]] for p in pts]
    return {"columns": [{"name": "lat", "type": "double"}, {"name": "lon", "type": "double"}, {"name": "name", "type": "text"}],
            "rows": rows, "geometry": {"lat": "lat", "lon": "lon"}}
''',
        "test": """[[cases]]
name = "دو نقطه"
file = '''{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[51.4,35.7]},"properties":{"name":"a"}},{"type":"Feature","geometry":{"type":"Point","coordinates":[52,36]},"properties":{}}]}'''
[cases.expect]
rows_count = 2
"""},
    "exporter_geojson": {
        "role": "exporter", "title": "خروجی GeoJSON", "hint": "ردیف‌های یک جدول (تا ۵۰۰۰) به‌صورت نقطه با ویژگی‌ها", "needs": ["table", "lat", "lon"],
        "source": '''import geo


def handle(ctx, params):
    r = ctx.sql('select * from "@TABLE@" limit 5000')
    rows = [dict(zip(r["columns"], row, strict=False)) for row in r["rows"]]
    return {"filename": "@TABLE@", "text": geo.to_geojson_points(rows, "@LAT@", "@LON@")}
''',
        "test": '''[[cases]]
name = "یک نقطه"
[[cases.sql]]
match = "select"
columns = ["name", "@LAT@", "@LON@"]
rows = [["a", 35.7, 51.4]]
[cases.expect]
text_contains = "FeatureCollection"
'''},
    "ingest_csv_lines": {
        "role": "ingest", "title": "تبدیل متن خط‌به‌خط دستگاه", "hint": "هر خط «دستگاه,عرض,طول[,سرعت]»؛ فیلدهای دریافت داده device، lat، lon و speed باشند", "needs": [],
        "source": '''def handle(ctx, params):
    rows = []
    for line in ctx.file().decode("utf-8-sig").splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) < 3 or not p[0]:
            continue
        rows.append({"device": p[0], "lat": float(p[1]), "lon": float(p[2]), "speed": float(p[3]) if len(p) > 3 and p[3] else None})
    return {"rows": rows}
''',
        "test": '''[[cases]]
name = "دو خط"
file = "d1,35.7,51.4,42\\nd2,36,52"
[cases.expect]
rows_count = 2
'''},
    "alert_threshold": {
        "role": "alert", "title": "هشدار آستانه (مثلاً سطح آب، رطوبت، دما)", "hint": "اگر بیشینه‌ی ستون از آستانه بگذرد، به مالک پایگاه داده پیام می‌دهد", "needs": ["table", "num"],
        "nums": ["threshold"], "every": 60,
        "source": '''THRESHOLD = @THRESHOLD@


def handle(ctx, params):
    v = ctx.sql('select max("@NUM@") from "@TABLE@"')["rows"][0][0]
    if v is not None and v > THRESHOLD:
        return {"alerts": [{"title": "عبور از آستانه", "body": f"بیشینه‌ی @NUM@ برابر {v} است (آستانه {THRESHOLD})."}]}
    return {"alerts": []}
''',
        "test": '''[[cases]]
name = "زیر آستانه"
[[cases.sql]]
match = "select"
columns = ["v"]
rows = [[@LOW@]]
[cases.expect]
alerts_count = 0

[[cases]]
name = "بالای آستانه"
[[cases.sql]]
match = "select"
columns = ["v"]
rows = [[@HIGH@]]
[cases.expect]
alerts_count = 1
'''},
    "block_blank": {"role": "block", "title": "بلوک خالی (برای نوشتن دستی)", "hint": "نقطه‌ی شروع با ctx.sql", "needs": [],
                    "source": 'def handle(ctx, params):\n    r = ctx.sql("select 1 as n")\n    return {"columns": ["شاخص", "مقدار"], "rows": [["نمونه", r["rows"][0][0]]]}\n',
                    "test": BLOCK_TEST.format(cols='"n"', rows="[[1]]", n=1).replace('match = "select"', 'match = "select 1"')},
    "importer_blank": {"role": "importer", "title": "ورود فایل خالی (برای نوشتن دستی)", "hint": "نقطه‌ی شروع با ctx.file()", "needs": [],
                       "source": 'def handle(ctx, params):\n    rows = []\n    for line in ctx.file().decode("utf-8").splitlines():\n        a, b = line.split(",")\n        rows.append([a, float(b)])\n    return {"columns": [{"name": "name", "type": "text"}, {"name": "value", "type": "double"}], "rows": rows}\n',
                       "test": '[[cases]]\nname = "دو ردیف"\nfile = "a,1.5\\nb,2"\n[cases.expect]\nrows_count = 2\n'},
}


def _ident(v: str, what: str) -> str:
    if not IDENT_RE.fullmatch(v or ""):
        raise WizardError(f"{what} نامعتبر است.")
    return v


def build(spec: dict, template: str, params: dict) -> dict:
    """قالب + پارامترهای اعتبارسنجی‌شده ← {role, source, test, every}. WizardError با پیام فارسی."""
    t = TEMPLATES.get(template)
    if t is None:
        raise WizardError("قالب نامعتبر است.")
    sub: dict[str, str] = {}
    tbl = None
    if "table" in t["needs"]:
        tbl = table_map(spec).get(params.get("table", ""))
        if tbl is None:
            raise WizardError("جدول را از فهرست جدول‌های مرحله‌ی «داده» انتخاب کنید.")
        sub["@TABLE@"] = _ident(tbl["name"], "نام جدول")
    for key in t["needs"]:
        if key == "table":
            continue
        label, types = COLS[key]
        col = columns_of(tbl).get(params.get(key, ""))
        if col is None or col["type"] not in types:
            raise WizardError(f"«{label}» را از ستون‌های جدول (نوع {'، '.join(types)}) انتخاب کنید.")
        sub[f"@{key.upper()}@"] = _ident(col["name"], label)
    for key in t.get("nums", []):
        label, lo, hi = NUMS[key]
        try:
            v = float(params.get(key, ""))
        except (TypeError, ValueError):
            raise WizardError(f"«{label}» عدد باشد.") from None
        if not lo <= v <= hi or v != v:
            raise WizardError(f"«{label}» بین {lo:g} و {hi:g} باشد.")
        sub[f"@{key.upper()}@"] = repr(v)
        if key == "threshold":
            sub["@LOW@"], sub["@HIGH@"] = repr(v - 1), repr(v + 1)
    source, test = t["source"], t["test"]
    for k, v in sub.items():
        source, test = source.replace(k, v), test.replace(k, v)
    out = {"role": t["role"], "source": source, "test": test, "every": t.get("every"), "tables": [tbl["name"]] if tbl else []}
    check_source(source)
    return out


def check_source(source: str, name: str = "code") -> None:
    """بررسی ایستای AST (همان جعبه)؛ WizardError با شماره‌ی خط."""
    if len(source) > MAX_SOURCE:
        raise WizardError(f"کد بیش از {MAX_SOURCE} نویسه است.")
    found = scan.scan(source, f"{name}.py")
    if found:
        raise WizardError("بررسی ایستای کد: " + "؛ ".join(found[:3]))


def validate_code(spec: dict) -> None:
    """همه‌ی handlerهای مشخصات: نام، نقش، سقف تعداد و بررسی ایستا."""
    code = spec.get("code") or {}
    if len(code) > MAX_HANDLERS:
        raise WizardError(f"حداکثر {MAX_HANDLERS} handler.")
    for name, h in code.items():
        if not NAME_RE.fullmatch(name):
            raise WizardError(f"نام handler «{name}» نامعتبر است (حروف کوچک لاتین، رقم و _؛ ۲ تا ۳۱ نویسه).")
        if h.get("role") not in ROLES:
            raise WizardError(f"نقش handler «{name}» نامعتبر است.")
        check_source(h.get("source", ""), name)
        if h["role"] == "alert":
            e = h.get("every")
            if not isinstance(e, int) or isinstance(e, bool) or not 5 <= e <= 1440:
                raise WizardError(f"فاصله‌ی هشدار «{name}» بین ۵ و ۱۴۴۰ دقیقه باشد.")


# ---------------------------------------------------------------------- آزمون ساخت‌یافته ← TOML آزمون (kernel.pkgtest)
MAX_CASES, MAX_SQL_MOCKS, MAX_MOCK_ROWS, MAX_FILE_TEXT = 10, 6, 200, 100_000
EXPECT_INT = ("rows_count", "alerts_count")
EXPECT_STR = ("text_contains", "error_contains")
SCALAR = (str, int, float, bool, type(None))


def _json_ok(v, depth=0) -> bool:
    if depth > 6:
        return False
    if isinstance(v, SCALAR):
        return True
    if isinstance(v, list):
        return len(v) <= 500 and all(_json_ok(x, depth + 1) for x in v)
    if isinstance(v, dict):
        return len(v) <= 100 and all(isinstance(k, str) and _json_ok(x, depth + 1) for k, x in v.items())
    return False


def normalize_cases(cases) -> list[dict]:
    """موردهای آزمون ساخت‌یافته را می‌سنجد و پاک‌سازی‌شده برمی‌گرداند؛ WizardError با پیام فارسی."""
    if not isinstance(cases, list) or not cases:
        raise WizardError("دست‌کم یک مورد آزمون لازم است.")
    if len(cases) > MAX_CASES:
        raise WizardError(f"حداکثر {MAX_CASES} مورد آزمون.")
    out = []
    for i, c in enumerate(cases, 1):
        if not isinstance(c, dict):
            raise WizardError(f"مورد {i} نامعتبر است.")
        name = str(c.get("name") or f"مورد {i}").strip()[:80]
        item: dict = {"name": name}
        params = c.get("params")
        if params not in (None, {}, ""):
            if not isinstance(params, dict) or not _json_ok(params):
                raise WizardError(f"«{name}»: ورودی باید یک شیء JSON ساده باشد.")
            item["params"] = params
        file = c.get("file")
        if file not in (None, ""):
            if not isinstance(file, str) or len(file) > MAX_FILE_TEXT:
                raise WizardError(f"«{name}»: فایل نمونه متن حداکثر {MAX_FILE_TEXT:,} نویسه است.")
            item["file"] = file
        sqls = []
        for m in c.get("sql") or []:
            if not isinstance(m, dict) or not str(m.get("match", "")).strip():
                raise WizardError(f"«{name}»: هر پاسخ ساختگی SQL باید عبارت تطبیق داشته باشد.")
            cols, rows = m.get("columns") or [], m.get("rows") or []
            if not isinstance(cols, list) or not all(isinstance(x, str) and x for x in cols) or not isinstance(rows, list):
                raise WizardError(f"«{name}»: ستون‌ها و ردیف‌های پاسخ ساختگی نامعتبر است.")
            if len(rows) > MAX_MOCK_ROWS or not all(isinstance(r, list) and len(r) == len(cols) and all(isinstance(x, SCALAR) for x in r) for r in rows):
                raise WizardError(f"«{name}»: هر ردیف ساختگی باید به‌اندازه‌ی ستون‌ها مقدار ساده داشته باشد (حداکثر {MAX_MOCK_ROWS} ردیف).")
            sqls.append({"match": str(m["match"]).strip()[:200], "columns": cols, "rows": rows})
        if len(sqls) > MAX_SQL_MOCKS:
            raise WizardError(f"«{name}»: حداکثر {MAX_SQL_MOCKS} پاسخ ساختگی SQL.")
        if sqls:
            item["sql"] = sqls
        exp = c.get("expect")
        if not isinstance(exp, dict) or len(exp) != 1:
            raise WizardError(f"«{name}»: دقیقاً یک انتظار انتخاب کنید.")
        (k, v), = exp.items()
        if k in EXPECT_INT:
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 100000:
                raise WizardError(f"«{name}»: مقدار انتظار عدد صحیح نامنفی است.")
        elif k in EXPECT_STR:
            if not isinstance(v, str) or not v.strip():
                raise WizardError(f"«{name}»: متن انتظار را بنویسید.")
        elif k == "equals":
            if not isinstance(v, (dict, list)) or not _json_ok(v):
                raise WizardError(f"«{name}»: «برابر با» یک شیء یا فهرست JSON ساده است.")
        else:
            raise WizardError(f"«{name}»: نوع انتظار ناشناخته است.")
        item["expect"] = {k: v}
        out.append(item)
    return out


def cases_toml(cases) -> str:
    """موردهای ساخت‌یافته ← متن `tests/<handler>.toml`؛ خروجی همیشه از pkgtest.parse می‌گذرد."""
    from . import pkgtest

    norm = normalize_cases(cases)
    lines: list[str] = []
    for c in norm:
        lines += ["[[cases]]", f"name = {_val(c['name'])}"]
        if "params" in c:
            lines.append(f"params = {_val(c['params'])}")
        if "file" in c:
            lines.append(f"file = {_val(c['file'])}")
        for m in c.get("sql", []):
            lines += ["[[cases.sql]]", f"match = {_val(m['match'])}", f"columns = {_val(m['columns'])}", f"rows = {_val(m['rows'])}"]
        lines.append("[cases.expect]")
        (k, v), = c["expect"].items()
        lines += [f"{_key(k)} = {_val(v)}", ""]
    text = "\n".join(lines)
    try:
        pkgtest.parse(text, "draft")
    except pkgtest.TestSpecError as exc:
        raise WizardError(f"آزمون: {exc}") from exc
    return text


def cases_from_toml(text: str) -> list[dict]:
    """متن آزمون (قالب یا دستی) ← موردهای ساخت‌یافته؛ [] اگر نخوانده شد یا از قالب ساخت‌یافته بیرون است (مثلاً چند انتظار)."""
    try:
        raw = tomllib.loads(text or "").get("cases") or []
        out = []
        for c in raw:
            exp = c.get("expect") or {}
            if len(exp) != 1:
                return []
            out.append({k: v for k, v in {"name": c.get("name"), "params": c.get("params"), "file": c.get("file"), "sql": c.get("sql"), "expect": exp}.items() if v is not None})
        return normalize_cases(out)
    except (tomllib.TOMLDecodeError, WizardError, AttributeError, TypeError):
        return []
