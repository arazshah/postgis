"""کیت صفحه: پلاگین HTML و CSS نمی‌نویسد؛ صفحه را با «مشخصات» (داده) توصیف می‌کند و هسته آن را با اجزای سیستم طراحی می‌سازد.

یکدستی (راست‌به‌چپ، ۴۰۰ پیکسل، حالت خالی و خطا) به‌طور ساختاری تضمین است، نه با بازبینی.

بلوک‌ها: text، kpi، table، bars، map. منبع داده‌ی هر بلوک یک `SELECT` است که فقط **خواندنی** و با نقش محدود مرورگر روی
پایگاه همان مشتری اجرا می‌شود (تراکنش فقط‌خواندنی، حد زمانی، سقف ردیف، یک دستور). مقدارهای پارامتر همیشه bind می‌شوند
(`%(name)s`)؛ نام جدول فقط از پارامتر نوع `layer` و با `sql.Identifier` (`{name}`) داخل SQL می‌آید.

نویسه‌ی `%` واقعی در SQL را `%%` و `{`/`}` واقعی را `{{`/`}}` بنویسید.
"""
from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from psycopg import sql

from . import geomval, nav, tenantdb
from .plugins import registry

POINT = "page.spec"
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
PARAM_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
BLOCKS = ("text", "kpi", "table", "bars", "map")
WIDTHS = ("full", "half", "third")
PARAM_KINDS = ("int", "number", "text", "choice", "layer")
GROUPS = ("data", "share", "manage")
NEEDS = ("viewer", "editor", "owner")
TIMEOUT_S = 8
MAX_SQL = 4000
LIMITS = {"table": 200, "bars": 50, "map": 2000, "kpi": 1}


class SpecError(ValueError):
    """مشخصات صفحه نامعتبر است (پیام فارسی برای گزارش بررسی بسته)."""


@dataclass(frozen=True)
class Param:
    name: str
    kind: str
    label: str
    default: str = ""
    choices: tuple[tuple[str, str], ...] = ()
    min: float | None = None
    max: float | None = None


@dataclass(frozen=True)
class Block:
    kind: str
    title: str = ""
    width: str = "full"
    sql: str = ""
    text: str = ""
    unit: str = ""
    hint: str = ""
    columns: tuple[tuple[str, str], ...] = ()  # (نام ستون، برچسب)
    handler: str = ""  # سطح ۲: نام handler کد ایزوله به‌جای sql (پاسخ: {"columns": [...], "rows": [[...]]})


FIELD_KINDS = ("text", "int", "number", "bool", "date", "choice", "geometry")
GEOM_KINDS = ("point", "line", "polygon", "multipolygon")
MAX_FORMS, MAX_FIELDS, MAX_VALUE = 3, 12, 2000
TABLE_RE = re.compile(r"[a-z_][a-z0-9_]{0,62}(\.[a-z_][a-z0-9_]{0,62})?")


@dataclass(frozen=True)
class Field:
    name: str  # نام ستون جدول مقصد
    kind: str
    label: str
    required: bool = False
    choices: tuple[tuple[str, str], ...] = ()
    max: float | None = None  # برای متن: حداکثر طول؛ برای عدد: سقف
    min: float | None = None
    geom: str = ""  # فقط kind = geometry: point | line | polygon | multipolygon


@dataclass(frozen=True)
class Form:
    """فرم ثبت یک ردیف: **فقط INSERT** در یک جدول مشخص؛ SQL را خود هسته می‌سازد، نه پلاگین."""

    key: str
    title: str
    table: str  # «schema.table» یا «table» (public)
    fields: tuple[Field, ...]
    submit: str = "ثبت"
    hint: str = ""
    success: str = "ثبت شد."


@dataclass(frozen=True)
class RecordSpec:
    """ویرایش و حذف ردیف‌های یک جدول **همین پلاگین** (ADR-0009 مرحله‌ی ۳): UPDATE/DELETE فقط روی `id` و فقط ستون‌های
    اعلام‌شده در `fields` را هسته می‌سازد (پارامتری)؛ SQL نوشتنی از پلاگین پذیرفته نمی‌شود. جدول باید در `[[tables]]` همین صفحه باشد."""

    key: str
    title: str
    table: str
    fields: tuple[Field, ...]
    columns: tuple[str, ...]  # ستون‌های نمایشی فهرست (غیرهندسه)
    can_delete: bool = True
    limit: int = 50
    hint: str = ""


COLUMN_TYPES = ("text", "integer", "bigint", "double", "boolean", "date", "timestamptz", "jsonb", "point", "line", "polygon", "multipolygon")
MAX_TABLES, MAX_COLUMNS, MAX_INDEXES = 5, 40, 3


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    type: str  # از COLUMN_TYPES؛ «point» = geometry(Point, 4326)
    required: bool = False  # NOT NULL (فقط هنگام ساخت جدول)
    auto_now: bool = False  # فقط timestamptz: DEFAULT now()


@dataclass(frozen=True)
class TableSpec:
    """جدولی که پلاگین لازم دارد (docs/adr/0008): هسته هنگام نخستین استفاده در پایگاه همان مشتری می‌سازد؛ فقط افزایشی."""

    name: str  # باید با «<id پلاگین>_» شروع شود؛ همیشه در public
    columns: tuple[ColumnSpec, ...]
    indexes: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class IngestSpec:
    """نقطه‌ی دریافت داده‌ی دستگاه (docs/plugins/ingest.md): نشانی عمومی با توکن هر پایگاه؛ **فقط INSERT** در جدول مشخص با
    فیلدهای اعلام‌شده (هسته می‌سازد، مثل فرم). `handler` سطح ۲ اختیاری است: بدنه را به ردیف‌ها تبدیل می‌کند."""

    key: str
    title: str
    table: str
    fields: tuple[Field, ...]
    handler: str = ""
    max_rows: int = 100  # سقف ردیف در هر درخواست
    rate: int = 60  # سقف درخواست در دقیقه برای هر توکن
    hint: str = ""


@dataclass(frozen=True)
class ReportSpec:
    """گزارش PDF صفحه (ADR-0009 مرحله‌ی ۴): بلوک‌های انتخابی صفحه (شماره‌ی ۱-پایه؛ خالی = همه) با فیلترهای فعلی، با هدر،
    تاریخ شمسی و نقشه‌ی برداری. قالب را هسته می‌سازد، نه پلاگین."""

    key: str
    title: str
    blocks: tuple[int, ...] = ()
    landscape: bool = False
    subtitle: str = ""
    button: str = "گزارش PDF"


@dataclass(frozen=True)
class SourceInput:
    """مقدار قابل‌تنظیم هر پایگاه برای منبع (مثلاً عرض و طول جغرافیایی)."""

    name: str
    label: str
    kind: str = "number"  # number | int | text | choice (یکی از choices) | multi (چند تا از choices؛ با ویرگول به query می‌رود)
    required: bool = True
    default: str = ""
    min: float | None = None
    max: float | None = None
    choices: tuple[tuple[str, str], ...] = ()  # (مقدار، برچسب) برای choice و multi


@dataclass(frozen=True)
class SourceSpec:
    """واکشی دوره‌ای از API بیرونی (ADR-0009): **هسته** واکشی می‌کند (کد پلاگین شبکه ندارد) و با INSERT پارامتری می‌نویسد.

    `url` فقط https و بدون query؛ query از `query` (مقدارها با `{ورودی}`، `{since}`، `{today}`). میزبان باید در فهرست سفید مدیر باشد.
    `layout`: «rows» (آرایه‌ی اشیاء) یا «columns» (شیء از آرایه‌ها، مثل Open-Meteo) در `rows_path` (مسیر نقطه‌ای)."""

    key: str
    title: str
    url: str
    host: str
    path: str
    query: tuple[tuple[str, str], ...]
    table: str
    fields: tuple[Field, ...]
    paths: tuple[tuple[str, str], ...]  # (نام ستون، مسیر در پاسخ)
    layout: str = "rows"
    rows_path: str = ""
    cursor: str = ""  # نام فیلدی که مقدار بیشینه‌اش پایه‌ی «فقط تازه‌ها» است
    every_minutes: int = 180
    since_days: int = 2
    inputs: tuple[SourceInput, ...] = ()
    secret_header: str = ""
    secret_param: str = ""
    hint: str = ""
    optional: tuple[str, ...] = ()  # ستون‌هایی که اگر در پاسخ نبودند NULL می‌شوند (مثلاً متغیری که کاربر انتخاب نکرده)
    consts: tuple[tuple[str, str], ...] = ()  # (ستون، نام ورودی): مقدار ستون از ورودی پایگاه می‌آید نه پاسخ (مثل lat، lon، model)
    mode: str = "append"  # append (فقط تازه‌تر از cursor) | replace (پنجره‌ی هم‌پوشان با همان consts پاک و دوباره نوشته می‌شود؛ برای پیش‌بینی)


@dataclass(frozen=True)
class ImportSpec:
    """ورود فایل با handler سطح ۲ (docs/adr/0005): کاربر فایل و نام جدول تازه می‌دهد؛ هسته جدول را می‌سازد."""

    key: str
    title: str
    handler: str
    extensions: tuple[str, ...] = ()
    hint: str = ""
    submit: str = "ورود فایل"
    success: str = "جدول ساخته شد."


@dataclass(frozen=True)
class ExportSpec:
    """خروجی اختصاصی با handler سطح ۲؛ فقط attachment با نوع محتوای فهرست سفید."""

    key: str
    title: str
    handler: str
    format: str = "csv"
    hint: str = ""
    submit: str = "دریافت خروجی"


@dataclass(frozen=True)
class Page:
    plugin: str
    key: str
    title: str
    subtitle: str = ""
    icon: str = "chart"
    group: str = "share"
    need: str = "viewer"
    order: int = 100
    refresh: int = 0  # ثانیه؛ ۰ = تازه‌سازی خودکار ندارد
    params: tuple[Param, ...] = ()
    blocks: tuple[Block, ...] = ()
    forms: tuple[Form, ...] = ()
    imports: tuple[ImportSpec, ...] = ()
    exports: tuple[ExportSpec, ...] = ()
    ingests: tuple[IngestSpec, ...] = ()
    tables: tuple[TableSpec, ...] = ()
    sources: tuple[SourceSpec, ...] = ()
    records: tuple[RecordSpec, ...] = ()
    reports: tuple[ReportSpec, ...] = ()


_icon_known = lambda name: True  # noqa: E731  هسته فهرست آیکون‌ها را نمی‌شناسد؛ پلاگین هسته‌ی سایت آن را ثبت می‌کند


def set_icon_checker(fn) -> None:
    global _icon_known
    _icon_known = fn


# ---------------------------------------------------------------------- اعتبارسنجی مشخصات
def _str(d: dict, k: str, *, required=False, limit=200, default="") -> str:
    v = d.get(k, default)
    if v is None:
        v = default
    if not isinstance(v, str):
        raise SpecError(f"«{k}» باید متن باشد.")
    v = v.strip()
    if required and not v:
        raise SpecError(f"«{k}» لازم است.")
    if len(v) > limit:
        raise SpecError(f"«{k}» بیش از {limit} نویسه است.")
    return v


def _sql_fields(text: str) -> set[str]:
    try:
        return {f for _lit, f, _s, _c in string.Formatter().parse(text) if f is not None}
    except ValueError as exc:
        raise SpecError(f"آکولاد در SQL نامعتبر است (آکولاد واقعی را دوبار بنویسید): {exc}") from exc


def _sql_values(text: str) -> set[str]:
    return set(re.findall(r"%\((\w+)\)s", text))


def parse_param(d: dict) -> Param:
    name = _str(d, "name", required=True, limit=31)
    if not PARAM_RE.fullmatch(name):
        raise SpecError(f"نام پارامتر «{name}» نامعتبر است.")
    kind = _str(d, "kind", required=True)
    if kind not in PARAM_KINDS:
        raise SpecError(f"نوع پارامتر «{kind}» شناخته نیست.")
    choices = ()
    if kind == "choice":
        raw = d.get("choices") or []
        if not raw or not all(isinstance(c, (list, tuple)) and len(c) == 2 for c in raw):
            raise SpecError(f"پارامتر انتخابی «{name}» گزینه‌های [مقدار، برچسب] لازم دارد.")
        choices = tuple((str(a), str(b)) for a, b in raw)
    lo, hi = d.get("min"), d.get("max")
    for v in (lo, hi):
        if v is not None and not isinstance(v, (int, float)):
            raise SpecError(f"کران پارامتر «{name}» باید عدد باشد.")
    return Param(name, kind, _str(d, "label", required=True, limit=80), _str(d, "default", limit=100), choices, lo, hi)


def parse_block(d: dict, params: dict[str, Param]) -> Block:
    kind = _str(d, "kind", required=True)
    if kind not in BLOCKS:
        raise SpecError(f"نوع بلوک «{kind}» شناخته نیست (مجاز: {'، '.join(BLOCKS)}).")
    width = _str(d, "width", default="third" if kind == "kpi" else "full")
    if width not in WIDTHS:
        raise SpecError(f"عرض بلوک «{width}» نامعتبر است.")
    text, query = _str(d, "text", limit=4000), _str(d, "sql", limit=MAX_SQL)
    handler = _str(d, "handler", limit=31)
    if handler:
        if not KEY_RE.fullmatch(handler):
            raise SpecError(f"نام handler «{handler}» نامعتبر است.")
        if kind not in ("kpi", "table", "bars"):
            raise SpecError("handler فقط برای بلوک‌های kpi، table و bars است.")
        if query:
            raise SpecError("بلوک هم‌زمان «sql» و «handler» نمی‌تواند داشته باشد.")
    if kind == "text" and not text:
        raise SpecError("بلوک متنی باید «text» داشته باشد.")
    if kind != "text" and not handler:
        if not query:
            raise SpecError(f"بلوک «{kind}» باید «sql» داشته باشد.")
        if not re.match(r"^\s*(select|with)\b", query, re.I):
            raise SpecError("منبع داده فقط می‌تواند SELECT یا WITH باشد.")
        for f in _sql_fields(query):
            if f not in params or params[f].kind != "layer":
                raise SpecError(f"جای‌نگهدار {{{f}}} فقط برای پارامتر نوع layer مجاز است.")
        missing = _sql_values(query) - set(params)
        if missing:
            raise SpecError(f"پارامتر اعلام‌نشده در SQL: {'، '.join(sorted(missing))}")
        if any(params[v].kind == "layer" for v in _sql_values(query) if v in params):
            raise SpecError("پارامتر layer را با {نام} بیاورید، نه %(نام)s.")
    cols = d.get("columns") or []
    if cols and not all(isinstance(c, (list, tuple)) and len(c) == 2 for c in cols):
        raise SpecError("«columns» فهرست [نام ستون، برچسب] است.")
    return Block(kind, _str(d, "title", limit=100), width, query, text, _str(d, "unit", limit=20),
                 _str(d, "hint", limit=200), tuple((str(a), str(b)) for a, b in cols), handler)


def parse_field(d: dict) -> Field:
    name = _str(d, "name", required=True, limit=63)
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", name):
        raise SpecError(f"نام ستون «{name}» نامعتبر است.")
    kind = _str(d, "kind", default="text")
    if kind not in FIELD_KINDS:
        raise SpecError(f"نوع فیلد «{kind}» شناخته نیست.")
    choices = ()
    if kind == "choice":
        raw = d.get("choices") or []
        if not raw or not all(isinstance(c, (list, tuple)) and len(c) == 2 for c in raw):
            raise SpecError(f"فیلد انتخابی «{name}» گزینه‌های [مقدار، برچسب] لازم دارد.")
        choices = tuple((str(a), str(b)) for a, b in raw)
    lo, hi = d.get("min"), d.get("max")
    for v in (lo, hi):
        if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool)):
            raise SpecError(f"کران فیلد «{name}» باید عدد باشد.")
    geom = ""
    if kind == "geometry":
        geom = _str(d, "geom", default="polygon")
        if geom not in GEOM_KINDS:
            raise SpecError(f"نوع هندسه‌ی فیلد «{name}» یکی از {'، '.join(GEOM_KINDS)} است.")
    return Field(name, kind, _str(d, "label", required=True, limit=80), bool(d.get("required", False)), choices, hi, lo, geom)


def parse_form(d: dict) -> Form:
    key = _str(d, "key", required=True, limit=31)
    if not KEY_RE.fullmatch(key):
        raise SpecError(f"کلید فرم «{key}» نامعتبر است.")
    table = _str(d, "table", required=True, limit=127)
    if not TABLE_RE.fullmatch(table):
        raise SpecError(f"نام جدول «{table}» نامعتبر است (فقط schema.table با حروف کوچک لاتین).")
    fields = [parse_field(f) for f in d.get("fields") or []]
    if not fields:
        raise SpecError("فرم دست‌کم یک فیلد لازم دارد.")
    if len(fields) > MAX_FIELDS:
        raise SpecError(f"حداکثر {MAX_FIELDS} فیلد در هر فرم.")
    if len({f.name for f in fields}) != len(fields):
        raise SpecError("ستون‌های فرم باید یکتا باشند.")
    return Form(key, _str(d, "title", required=True, limit=80), table, tuple(fields),
                _str(d, "submit", default="ثبت", limit=30), _str(d, "hint", limit=240),
                _str(d, "success", default="ثبت شد.", limit=120))


def parse_table(plugin: str, d: dict) -> TableSpec:
    name = _str(d, "name", required=True, limit=63)
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,62}", name) or not name.startswith(f"{plugin}_") or name == f"{plugin}_":
        raise SpecError(f"نام جدول «{name}» باید با «{plugin}_» شروع شود (حروف کوچک لاتین، رقم و _).")
    raw = d.get("columns") or []
    if not raw or not isinstance(raw, list):
        raise SpecError(f"جدول «{name}» دست‌کم یک ستون لازم دارد.")
    if len(raw) > MAX_COLUMNS:
        raise SpecError(f"حداکثر {MAX_COLUMNS} ستون در هر جدول.")
    cols = []
    for c in raw:
        if not isinstance(c, dict):
            raise SpecError("هر ستون یک شیء است.")
        cname = _str(c, "name", required=True, limit=63)
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", cname) or cname in ("id", "geom") and c.get("type") not in GEOM_KINDS:
            raise SpecError(f"نام ستون «{cname}» نامعتبر یا رزروشده است (id را هسته می‌سازد).")
        ctype = _str(c, "type", default="text")
        if ctype not in COLUMN_TYPES:
            raise SpecError(f"نوع ستون «{ctype}» مجاز نیست (مجاز: {'، '.join(COLUMN_TYPES)}).")
        auto = bool(c.get("auto_now", False))
        if auto and ctype != "timestamptz":
            raise SpecError("auto_now فقط برای timestamptz است.")
        cols.append(ColumnSpec(cname, ctype, bool(c.get("required", False)), auto))
    if len({c.name for c in cols}) != len(cols):
        raise SpecError(f"ستون‌های جدول «{name}» باید یکتا باشند.")
    idx = d.get("indexes") or []
    if not isinstance(idx, list) or len(idx) > MAX_INDEXES:
        raise SpecError(f"حداکثر {MAX_INDEXES} شاخص.")
    indexes = []
    for i in idx:
        if not isinstance(i, list) or not i or len(i) > 3 or not all(isinstance(x, str) and x in {c.name for c in cols} for x in i):
            raise SpecError("هر شاخص فهرستی از ۱ تا ۳ نام ستونِ همین جدول است.")
        indexes.append(tuple(i))
    return TableSpec(name, tuple(cols), tuple(indexes))


def parse_ingest(d: dict) -> IngestSpec:
    key = _str(d, "key", required=True, limit=31)
    if not KEY_RE.fullmatch(key):
        raise SpecError(f"کلید دریافت «{key}» نامعتبر است.")
    table = _str(d, "table", required=True, limit=127)
    if not TABLE_RE.fullmatch(table):
        raise SpecError(f"نام جدول «{table}» نامعتبر است (فقط schema.table با حروف کوچک لاتین).")
    fields = [parse_field(f) for f in d.get("fields") or []]
    if not fields:
        raise SpecError("نقطه‌ی دریافت دست‌کم یک فیلد لازم دارد.")
    if len(fields) > MAX_FIELDS:
        raise SpecError(f"حداکثر {MAX_FIELDS} فیلد.")
    if len({f.name for f in fields}) != len(fields):
        raise SpecError("فیلدها باید یکتا باشند.")
    handler = _handler_name(d) if d.get("handler") else ""
    out = []
    for name, default, lo, hi in (("max_rows", 100, 1, 1000), ("rate", 60, 1, 600)):
        v = d.get(name, default)
        if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
            raise SpecError(f"«{name}» عددی بین {lo} و {hi} است.")
        out.append(v)
    return IngestSpec(key, _str(d, "title", required=True, limit=80), table, tuple(fields), handler, out[0], out[1],
                      _str(d, "hint", limit=240))


SRC_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}(\.[A-Za-z0-9_]{1,40}){0,5}$")
SRC_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")


def valid_host(h: str) -> bool:
    """نام دامنه‌ی عمومی (دست‌کم دو بخش، برچسب آخر غیرعددی ⇒ نشانی IP پذیرفته نیست)."""
    return bool(SRC_HOST_RE.fullmatch(h)) and not h.rsplit(".", 1)[-1].isdigit()


SRC_HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{1,39}$")
PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]{0,30})\}")
SRC_BUILTIN = ("since", "today")
MAX_SOURCE_FIELDS = 40


def parse_report(d: dict) -> ReportSpec:
    key = _str(d, "key", required=True, limit=31)
    if not KEY_RE.fullmatch(key):
        raise SpecError(f"کلید گزارش «{key}» نامعتبر است.")
    raw = d.get("blocks") or []
    if not isinstance(raw, list) or len(raw) > 24 or not all(isinstance(i, int) and not isinstance(i, bool) and i >= 1 for i in raw) \
            or len(set(raw)) != len(raw):
        raise SpecError("«blocks» فهرست شماره‌های یکتای بلوک (از ۱) است.")
    orient = _str(d, "orientation", default="portrait")
    if orient not in ("portrait", "landscape"):
        raise SpecError("«orientation» یکی از portrait یا landscape است.")
    return ReportSpec(key, _str(d, "title", required=True, limit=80), tuple(raw), orient == "landscape", _str(d, "subtitle", limit=240),
                      _str(d, "button", default="گزارش PDF", limit=30))


def parse_record(d: dict) -> RecordSpec:
    key = _str(d, "key", required=True, limit=31)
    if not KEY_RE.fullmatch(key):
        raise SpecError(f"کلید ویرایش ردیف «{key}» نامعتبر است.")
    table = _str(d, "table", required=True, limit=127)
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,62}", table):
        raise SpecError(f"جدول «{table}» نامعتبر است (فقط جدولی از [[tables]] همین صفحه، بدون schema).")
    fields = [parse_field(f) for f in d.get("fields") or []]
    if not fields or len(fields) > MAX_FIELDS or len({f.name for f in fields}) != len(fields):
        raise SpecError(f"ویرایش ردیف ۱ تا {MAX_FIELDS} فیلد یکتا می‌خواهد.")
    plain = [f.name for f in fields if f.kind != "geometry"]
    cols = d.get("columns")
    if cols is None:
        cols = plain[:4]
    if not isinstance(cols, list) or not cols or len(cols) > 6 or not all(isinstance(c, str) and c in plain for c in cols):
        raise SpecError("«columns» فهرست ۱ تا ۶ نام فیلدِ غیرهندسه‌ی همین ویرایش است.")
    limit = d.get("limit", 50)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise SpecError("«limit» عددی بین ۱ و ۱۰۰ است.")
    return RecordSpec(key, _str(d, "title", required=True, limit=80), table, tuple(fields), tuple(cols),
                      bool(d.get("can_delete", True)), limit, _str(d, "hint", limit=240))


def parse_source(d: dict) -> SourceSpec:
    from urllib.parse import urlsplit

    key = _str(d, "key", required=True, limit=31)
    if not KEY_RE.fullmatch(key):
        raise SpecError(f"کلید منبع «{key}» نامعتبر است.")
    url = _str(d, "url", required=True, limit=300)
    u = urlsplit(url)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment or u.port not in (None, 443):
        raise SpecError("نشانی منبع باید https بدون نام‌کاربری، پورت و پارامتر باشد (پارامترها در «query»).")
    host = u.hostname.lower()
    if not valid_host(host):
        raise SpecError("میزبان منبع نامعتبر است (نام دامنه؛ نشانی IP پذیرفته نیست).")
    if "{" in url or "%" in u.path:
        raise SpecError("نشانی منبع ثابت است؛ مقدار متغیر فقط در «query» می‌آید.")
    table = _str(d, "table", required=True, limit=127)
    if not TABLE_RE.fullmatch(table):
        raise SpecError(f"نام جدول «{table}» نامعتبر است.")
    layout = _str(d, "layout", default="rows")
    if layout not in ("rows", "columns"):
        raise SpecError("«layout» یکی از rows یا columns است.")
    rows_path = _str(d, "rows_path", limit=120)
    if rows_path and not SRC_PATH_RE.fullmatch(rows_path):
        raise SpecError("«rows_path» نامعتبر است (مسیر نقطه‌ای).")
    fields, paths, optional, const_pairs = [], [], [], []
    raw_fields = d.get("fields") or []
    if not raw_fields or len(raw_fields) > MAX_SOURCE_FIELDS:
        raise SpecError(f"منبع ۱ تا {MAX_SOURCE_FIELDS} فیلد لازم دارد.")
    for f in raw_fields:
        fd = parse_field(f)
        if fd.kind == "geometry":
            raise SpecError("فیلد هندسه برای منبع بیرونی پشتیبانی نمی‌شود.")
        if f.get("input"):  # ستون از ورودی پایگاه (نه پاسخ)
            const_pairs.append((fd.name, _str(f, "input", limit=30)))
        else:
            path = _str(f, "path", default=fd.name, limit=120)
            if not SRC_PATH_RE.fullmatch(path):
                raise SpecError(f"مسیر فیلد «{fd.name}» نامعتبر است.")
            paths.append((fd.name, path))
            if f.get("optional"):
                optional.append(fd.name)
        fields.append(fd)
    if len({f.name for f in fields}) != len(fields):
        raise SpecError("فیلدهای منبع باید یکتا باشند.")
    cursor = _str(d, "cursor", limit=63)
    if cursor and cursor not in {f.name for f in fields}:
        raise SpecError("«cursor» باید نام یکی از فیلدها باشد.")
    inputs = []
    for i in d.get("inputs") or []:
        name = _str(i, "name", required=True, limit=30)
        if not PARAM_RE.fullmatch(name) or name in SRC_BUILTIN:
            raise SpecError(f"نام ورودی «{name}» نامعتبر یا رزروشده است.")
        kind = _str(i, "kind", default="number")
        if kind not in ("number", "int", "text", "choice", "multi"):
            raise SpecError(f"نوع ورودی «{name}» نامعتبر است.")
        choices = ()
        if kind in ("choice", "multi"):
            rawc = i.get("choices") or []
            if not rawc or len(rawc) > 60 or not all(isinstance(c, (list, tuple)) and len(c) == 2 and re.fullmatch(r"[A-Za-z0-9_.:-]{1,60}", str(c[0])) for c in rawc):
                raise SpecError(f"ورودی «{name}» گزینه‌های [مقدار، برچسب] لازم دارد (مقدار: حروف لاتین، رقم و _.:-).")
            choices = tuple((str(a), str(b)) for a, b in rawc)
        lo, hi = i.get("min"), i.get("max")
        for v in (lo, hi):
            if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool)):
                raise SpecError(f"کران ورودی «{name}» باید عدد باشد.")
        inputs.append(SourceInput(name, _str(i, "label", required=True, limit=80), kind, bool(i.get("required", True)),
                                  _str(i, "default", limit=600), lo, hi, choices))
    if len(inputs) > 8 or len({i.name for i in inputs}) != len(inputs):
        raise SpecError("حداکثر ۸ ورودی یکتا.")
    in_names = {i.name for i in inputs}
    for col, inp in const_pairs:
        if inp not in in_names:
            raise SpecError(f"ستون «{col}» از ورودی «{inp}» می‌آید که اعلام نشده است.")
    mode = _str(d, "mode", default="append")
    if mode not in ("append", "replace"):
        raise SpecError("«mode» یکی از append یا replace است.")
    if mode == "replace" and not cursor:
        raise SpecError("حالت replace کلید زمانی (cursor) لازم دارد.")
    known = {i.name for i in inputs} | set(SRC_BUILTIN)
    raw_q = d.get("query") or {}
    if not isinstance(raw_q, dict) or len(raw_q) > 12:
        raise SpecError("«query» باید جدول کلید-مقدار (حداکثر ۱۲) باشد.")
    query = []
    for k, v in raw_q.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,39}", str(k)) or not isinstance(v, (str, int, float)) or isinstance(v, bool):
            raise SpecError(f"پارامتر «{k}» نامعتبر است.")
        v = str(v)
        if len(v) > 200 or set(PLACEHOLDER_RE.findall(v)) - known:
            raise SpecError(f"مقدار پارامتر «{k}» نامعتبر است (جای‌نگه‌دار ناشناخته یا طولانی).")
        if "{" in PLACEHOLDER_RE.sub("", v) or "}" in PLACEHOLDER_RE.sub("", v):
            raise SpecError(f"مقدار پارامتر «{k}»: آکولاد فقط برای جای‌نگه‌دار است.")
        query.append((str(k), v))
    sh, sp = _str(d, "secret_header", limit=40), _str(d, "secret_param", limit=40)
    if sh and sp:
        raise SpecError("فقط یکی از secret_header یا secret_param.")
    if sh and not SRC_HEADER_RE.fullmatch(sh):
        raise SpecError("نام هدر کلید API نامعتبر است.")
    if sp and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,39}", sp):
        raise SpecError("نام پارامتر کلید API نامعتبر است.")
    if sp and sp in dict(query):
        raise SpecError("نام پارامتر کلید API با query تکراری است.")
    out = []
    for name, default, lo, hi in (("every_minutes", 180, 15, 1440), ("since_days", 2, 1, 30)):
        v = d.get(name, default)
        if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
            raise SpecError(f"«{name}» عددی بین {lo} و {hi} است.")
        out.append(v)
    return SourceSpec(key, _str(d, "title", required=True, limit=80), url, host, u.path or "/", tuple(query), table, tuple(fields),
                      tuple(paths), layout, rows_path, cursor, out[0], out[1], tuple(inputs), sh, sp, _str(d, "hint", limit=240),
                      tuple(optional), tuple(const_pairs), mode)


EXT_RE = re.compile(r"\.[a-z0-9]{1,8}")
EXPORT_FORMATS = ("csv", "json", "txt", "geojson")


def _handler_name(d: dict) -> str:
    h = _str(d, "handler", required=True, limit=31)
    if not KEY_RE.fullmatch(h):
        raise SpecError(f"نام handler «{h}» نامعتبر است.")
    return h


def parse_import(d: dict) -> ImportSpec:
    key = _str(d, "key", required=True, limit=31)
    if not KEY_RE.fullmatch(key):
        raise SpecError(f"کلید ورود «{key}» نامعتبر است.")
    exts = d.get("extensions") or []
    if not isinstance(exts, list) or len(exts) > 8 or not all(isinstance(e, str) and EXT_RE.fullmatch(e) for e in exts):
        raise SpecError("extensions فهرست پسوندهایی مثل [\".trk\"] است (حداکثر ۸).")
    return ImportSpec(key, _str(d, "title", required=True, limit=80), _handler_name(d), tuple(exts), _str(d, "hint", limit=240),
                      _str(d, "submit", default="ورود فایل", limit=30), _str(d, "success", default="جدول ساخته شد.", limit=120))


def parse_export(d: dict) -> ExportSpec:
    key = _str(d, "key", required=True, limit=31)
    if not KEY_RE.fullmatch(key):
        raise SpecError(f"کلید خروجی «{key}» نامعتبر است.")
    fmt = _str(d, "format", default="csv")
    if fmt not in EXPORT_FORMATS:
        raise SpecError(f"قالب خروجی «{fmt}» نامعتبر است (مجاز: {'، '.join(EXPORT_FORMATS)}).")
    return ExportSpec(key, _str(d, "title", required=True, limit=80), _handler_name(d), fmt, _str(d, "hint", limit=240),
                      _str(d, "submit", default="دریافت خروجی", limit=30))


def parse_page(plugin: str, d: dict) -> Page:
    """مشخصات خام (dict از TOML/JSON) ← Page اعتبارسنجی‌شده. خطا = SpecError با پیام فارسی."""
    if not isinstance(d, dict):
        raise SpecError("مشخصات صفحه باید یک شیء باشد.")
    key = _str(d, "key", required=True, limit=31)
    if not KEY_RE.fullmatch(key):
        raise SpecError(f"کلید صفحه «{key}» نامعتبر است (حروف کوچک لاتین، رقم و _).")
    icon = _str(d, "icon", default="chart", limit=40)
    if not _icon_known(icon):
        raise SpecError(f"آیکون «{icon}» در مجموعه‌ی سیستم طراحی نیست.")
    group, need = _str(d, "group", default="share"), _str(d, "need", default="viewer")
    if group not in GROUPS:
        raise SpecError(f"گروه منو «{group}» نامعتبر است (مجاز: {'، '.join(GROUPS)}).")
    if need not in NEEDS:
        raise SpecError(f"سطح دسترسی «{need}» نامعتبر است.")
    refresh = d.get("refresh", 0)
    if not isinstance(refresh, int) or isinstance(refresh, bool) or not (refresh == 0 or 5 <= refresh <= 3600):
        raise SpecError("«refresh» صفر یا بین ۵ تا ۳۶۰۰ ثانیه است.")
    order = d.get("order", 100)
    if not isinstance(order, int) or isinstance(order, bool):
        raise SpecError("«order» باید عدد صحیح باشد.")
    params = [parse_param(p) for p in d.get("params") or []]
    if len({p.name for p in params}) != len(params):
        raise SpecError("نام پارامترها باید یکتا باشد.")
    by_name = {p.name: p for p in params}
    blocks = [parse_block(b, by_name) for b in d.get("blocks") or []]
    forms = [parse_form(f) for f in d.get("forms") or []]
    if len(forms) > MAX_FORMS:
        raise SpecError(f"حداکثر {MAX_FORMS} فرم در یک صفحه.")
    if len({f.key for f in forms}) != len(forms):
        raise SpecError("کلید فرم‌ها باید یکتا باشد.")
    if forms and need == "viewer":
        raise SpecError("صفحه‌ی دارای فرم (نوشتن) دست‌کم سطح «editor» می‌خواهد.")
    imports = [parse_import(i) for i in d.get("imports") or []]
    exports = [parse_export(e) for e in d.get("exports") or []]
    if len(imports) > 2 or len(exports) > 3:
        raise SpecError("حداکثر ۲ ورود و ۳ خروجی در یک صفحه.")
    if len({i.key for i in imports}) != len(imports) or len({e.key for e in exports}) != len(exports):
        raise SpecError("کلید ورودها و خروجی‌ها باید یکتا باشد.")
    if imports and need == "viewer":
        raise SpecError("صفحه‌ی دارای ورود فایل (نوشتن) دست‌کم سطح «editor» می‌خواهد.")
    tables = [parse_table(plugin, t) for t in d.get("tables") or []]
    if len(tables) > MAX_TABLES:
        raise SpecError(f"حداکثر {MAX_TABLES} جدول در یک صفحه.")
    if len({t.name for t in tables}) != len(tables):
        raise SpecError("نام جدول‌ها باید یکتا باشد.")
    ingests = [parse_ingest(i) for i in d.get("ingest") or []]
    if len(ingests) > 2:
        raise SpecError("حداکثر ۲ نقطه‌ی دریافت داده در یک صفحه.")
    if len({i.key for i in ingests}) != len(ingests):
        raise SpecError("کلید نقطه‌های دریافت باید یکتا باشد.")
    if ingests and need == "viewer":
        raise SpecError("صفحه‌ی دارای دریافت داده (نوشتن) دست‌کم سطح «editor» می‌خواهد.")
    sources = [parse_source(x) for x in d.get("sources") or []]
    if len(sources) > 2:
        raise SpecError("حداکثر ۲ منبع بیرونی در یک صفحه.")
    if len({x.key for x in sources}) != len(sources):
        raise SpecError("کلید منبع‌ها باید یکتا باشد.")
    if sources and need == "viewer":
        raise SpecError("صفحه‌ی دارای منبع بیرونی (نوشتن) دست‌کم سطح «editor» می‌خواهد.")
    records = [parse_record(x) for x in d.get("records") or []]
    if len(records) > 2 or len({x.key for x in records}) != len(records):
        raise SpecError("حداکثر ۲ ویرایش ردیف با کلید یکتا در یک صفحه.")
    own = {t.name for t in tables}
    for x in records:
        if x.table not in own:
            raise SpecError(f"ویرایش ردیف «{x.key}»: جدول «{x.table}» باید در [[tables]] همین صفحه اعلام شده باشد.")
    if records and need == "viewer":
        raise SpecError("صفحه‌ی دارای ویرایش ردیف (نوشتن) دست‌کم سطح «editor» می‌خواهد.")
    reports = [parse_report(x) for x in d.get("reports") or []]
    if len(reports) > 3 or len({x.key for x in reports}) != len(reports):
        raise SpecError("حداکثر ۳ گزارش با کلید یکتا در یک صفحه.")
    for x in reports:
        if any(i > len(blocks) for i in x.blocks):
            raise SpecError(f"گزارش «{x.key}»: شماره‌ی بلوک از تعداد بلوک‌های صفحه ({len(blocks)}) بیشتر است.")
    if not blocks:
        raise SpecError("صفحه دست‌کم یک بلوک لازم دارد.")
    if len(blocks) > 24:
        raise SpecError("حداکثر ۲۴ بلوک در یک صفحه.")
    return Page(plugin, key, _str(d, "title", required=True, limit=80), _str(d, "subtitle", limit=240), icon, group, need,
                order, refresh, tuple(params), tuple(blocks), tuple(forms), tuple(imports), tuple(exports), tuple(ingests), tuple(tables), tuple(sources), tuple(records), tuple(reports))


# ---------------------------------------------------------------------- ثبت
def register(plugin: str, page: Page) -> None:
    """صفحه را در رجیستری و منوی ریل پایگاه ثبت می‌کند (مدیریت دسترسی را موتور مجوز انجام می‌دهد)."""
    registry.add(POINT, f"{plugin}:{page.key}", page, plugin=plugin, order=page.order, replace=True)
    nav.ws_section(page.group, page.title, "kernel:page", page.icon, page.need, plugin=plugin, order=page.order,
                   views=("kernel:page",), extra=(plugin, page.key))


def unregister_plugin(plugin: str) -> None:
    """همه‌ی صفحه‌های یک پلاگین را برمی‌دارد (با remove_plugin رجیستری)."""
    registry.remove_plugin(plugin)


def get(plugin: str, key: str) -> Page | None:
    return registry.get(POINT, f"{plugin}:{key}")


def pages() -> list[Page]:
    return registry.values(POINT)


# ---------------------------------------------------------------------- مقدار پارامترها
def read_values(page: Page, query, layers: dict[str, str]) -> tuple[dict, list[str]]:
    """مقدارهای پارامتر از نشانی (GET) با اعتبارسنجی؛ مقدار نامعتبر = پیش‌فرض + پیام. layers: «schema.table» های مجاز."""
    values, errors = {}, []
    for p in page.params:
        raw = (query.get(p.name) if query is not None else None)
        raw = p.default if raw in (None, "") else raw
        try:
            values[p.name] = _convert(p, raw, layers)
        except (ValueError, KeyError):
            errors.append(f"مقدار «{p.label}» نامعتبر بود؛ مقدار پیش‌فرض به‌کار رفت.")
            try:
                values[p.name] = _convert(p, p.default, layers)
            except (ValueError, KeyError):
                values[p.name] = None
    return values, errors


def _convert(p: Param, raw, layers):
    if p.kind == "text":
        return str(raw)[:100]
    if p.kind == "choice":
        if str(raw) not in {c[0] for c in p.choices}:
            raise ValueError
        return str(raw)
    if p.kind == "layer":
        if str(raw) not in layers:
            raise ValueError
        return str(raw)
    num = int(raw) if p.kind == "int" else float(raw)
    if (p.min is not None and num < p.min) or (p.max is not None and num > p.max):
        raise ValueError
    return num


# ---------------------------------------------------------------------- اجرای منبع داده
def _compose(template: str, layer_values: dict[str, str]) -> sql.Composable:
    parts: list[sql.Composable] = []
    for literal, name, _spec, _conv in string.Formatter().parse(template):
        if literal:
            parts.append(sql.SQL(literal))
        if name is not None:
            schema, _, table = layer_values[name].partition(".")
            parts.append(sql.Identifier(schema, table))
    return sql.Composed(parts)


def run_sql(ws, block: Block, page: Page, values: dict, *, kind: str | None = None) -> tuple[list[str], list[tuple]]:
    """SELECT بلوک را فقط‌خواندنی اجرا می‌کند و (نام ستون‌ها، ردیف‌ها) برمی‌گرداند."""
    layer_values = {p.name: values[p.name] for p in page.params if p.kind == "layer" and values.get(p.name)}
    if any(f not in layer_values for f in _sql_fields(block.sql)):
        raise SpecError("لایه‌ی انتخاب‌شده برای این بلوک در دسترس نیست.")
    inner = _compose(block.sql, layer_values)
    limit = LIMITS.get(kind or block.kind, 200)
    if (kind or block.kind) == "map":
        query = sql.SQL(
            "SELECT ST_AsGeoJSON(CASE WHEN ST_SRID(q.geom::geometry) IN (0, 4326) THEN q.geom::geometry "
            "ELSE ST_Transform(q.geom::geometry, 4326) END)::text AS __geom, to_jsonb(q) - 'geom' AS __props "
            "FROM ({}) AS q WHERE q.geom IS NOT NULL LIMIT %(__limit)s").format(inner)
    else:
        query = sql.SQL("SELECT * FROM ({}) AS q LIMIT %(__limit)s").format(inner)
    args = {p.name: values.get(p.name) for p in page.params if p.kind != "layer"}
    args["__limit"] = limit
    with tenantdb.connect(ws) as conn:  # نقش محدود مرورگر + تراکنش فقط‌خواندنی
        conn.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(f"{TIMEOUT_S}s")))
        cur = conn.execute(query, args, prepare=True)  # پروتکل گسترده: فقط یک دستور
        cols = [d.name for d in cur.description]
        return cols, cur.fetchall()


def read_select(ws, query: str, params=None, *, limit: int = 2000) -> dict:
    """پل SQL برای کد سطح ۲: فقط SELECT/WITH، یک دستور، تراکنش فقط‌خواندنی با نقش محدود مشتری، سقف ردیف و زمان."""
    if not re.match(r"^\s*(select|with)\b", query or "", re.I) or len(query) > MAX_SQL:
        raise SpecError("فقط SELECT یا WITH (حداکثر ۴۰۰۰ نویسه) مجاز است.")
    with tenantdb.connect(ws) as conn:
        conn.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(f"{TIMEOUT_S}s")))
        cur = conn.execute(sql.SQL("SELECT * FROM ({}) AS q LIMIT {}").format(sql.SQL(query.rstrip().rstrip(";")), sql.Literal(limit)),
                           params if isinstance(params, (list, tuple, dict)) else None, prepare=True)
        cols = [d.name for d in cur.description]
        return {"columns": cols, "rows": [[_json_safe(v) for v in r] for r in cur.fetchall()]}


def _json_safe(v):
    if isinstance(v, (Decimal,)):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (bytes, memoryview)):
        return None
    return v


def run_handler(ws, page: Page, block: Block, values: dict) -> tuple[list[str], list[tuple]]:
    """بلوک مبتنی بر کد ایزوله: handler را اجرا و (ستون‌ها، ردیف‌ها) را برمی‌گرداند. خطا = SpecError با پیام کوتاه."""
    from .runner import client

    params = {p.name: values.get(p.name) for p in page.params if p.kind != "layer"}
    params.update({p.name: values.get(p.name) for p in page.params if p.kind == "layer"})
    try:
        out = client.execute(page.plugin, block.handler, params, lambda q, a: read_select(ws, q, a), getattr(ws, "pk", 0))
    except client.RunnerError as exc:
        raise SpecError(str(exc)) from exc
    if not isinstance(out, dict) or not isinstance(out.get("columns"), list) or not isinstance(out.get("rows"), list):
        raise SpecError("handler باید {columns: [...], rows: [[...]]} برگرداند.")
    cols = [str(c) for c in out["columns"]][:50]
    rows = [tuple(r) for r in out["rows"][:LIMITS.get(block.kind, 200)] if isinstance(r, (list, tuple))]
    return cols, rows


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "بله" if v else "خیر"
    if isinstance(v, (int, Decimal)) or (isinstance(v, float) and v.is_integer()):
        return f"{int(v):,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d %H:%M") if isinstance(v, datetime) else v.isoformat()
    s = str(v)
    return s if len(s) <= 200 else s[:200] + "…"


def render_block(ws, page: Page, block: Block, values: dict) -> dict:
    """مدل نمایش یک بلوک برای قالب. خطای داده فقط همین بلوک را به پیام کوتاه تبدیل می‌کند."""
    out = {"kind": block.kind, "title": block.title, "width": block.width, "hint": block.hint, "error": ""}
    if block.kind == "text":
        out["paras"] = [p.strip() for p in block.text.split("\n\n") if p.strip()]
        return out
    try:
        cols, rows = run_handler(ws, page, block, values) if block.handler else run_sql(ws, block, page, values)
    except SpecError as exc:
        out["error"] = str(exc)
        return out
    except Exception as exc:  # noqa: BLE001  خطای PostgreSQL: متن کوتاه برای کاربر، جزئیات برای مدیر
        msg = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        out["error"] = "زمان اجرا تمام شد؛ پرس‌وجو سنگین است." if "statement timeout" in msg else "خواندن داده ممکن نشد."
        out["detail"] = msg[:300]
        return out
    if block.kind == "kpi":
        v = rows[0][0] if rows and rows[0] else None
        out.update(value=_fmt(v) if v is not None else "—", unit=block.unit)
    elif block.kind == "table":
        labels = dict(block.columns)
        shown = [c for c, _l in block.columns] if block.columns else cols
        idx = [cols.index(c) for c in shown if c in cols]
        out.update(headers=[labels.get(cols[i], cols[i]) for i in idx], rows=[[_fmt(r[i]) for i in idx] for r in rows],
                   truncated=len(rows) >= LIMITS["table"])
    elif block.kind == "bars":
        lower = [c.lower() for c in cols]
        if "label" not in lower or "value" not in lower:
            out["error"] = "ستون‌های «label» و «value» لازم است."
            return out
        li, vi = lower.index("label"), lower.index("value")
        top = max([float(r[vi] or 0) for r in rows] + [1.0])
        out["bars"] = [{"label": _fmt(r[li]), "value": _fmt(r[vi]), "pct": round(float(r[vi] or 0) * 100 / top)} for r in rows]
    elif block.kind == "map":
        try:
            _cols, mrows = run_sql(ws, block, page, values, kind="map")
        except Exception as exc:  # noqa: BLE001
            out["error"] = "ستون «geom» با هندسه‌ی معتبر لازم است." if "geom" in str(exc) else "خواندن داده ممکن نشد."
            return out
        feats = [{"type": "Feature", "geometry": json.loads(g), "properties": props} for g, props in mrows]
        out["geojson"] = {"type": "FeatureCollection", "features": feats}
        out["count"] = len(feats)
    return out


# ---------------------------------------------------------------------- فرم ثبت ردیف (نوشتن)
def get_import(page: Page, key: str) -> ImportSpec | None:
    return next((i for i in page.imports if i.key == key), None)


def get_export(page: Page, key: str) -> ExportSpec | None:
    return next((e for e in page.exports if e.key == key), None)


def get_ingest(page: Page, key: str) -> IngestSpec | None:
    return next((i for i in page.ingests if i.key == key), None)


def get_report(page: Page, key: str) -> ReportSpec | None:
    return next((r for r in page.reports if r.key == key), None)


def get_record(page: Page, key: str) -> RecordSpec | None:
    return next((r for r in page.records if r.key == key), None)


def get_source(page: Page, key: str) -> SourceSpec | None:
    return next((x for x in page.sources if x.key == key), None)


def get_form(page: Page, key: str) -> Form | None:
    return next((f for f in page.forms if f.key == key), None)


def convert_field(f: Field, raw) -> object:
    """مقدار خام POST ← مقدار نوع‌دار؛ ValueError با پیام فارسی. خالی و غیراجباری = None."""
    text = (raw if raw is not None else "")
    text = text.strip() if isinstance(text, str) else str(text)
    if f.kind == "bool":
        return text in ("1", "true", "on")
    if text == "":
        if f.required:
            raise ValueError(f"«{f.label}» الزامی است.")
        return None
    if f.kind == "geometry":
        return geomval.validate(text, f.geom, f.label)
    if len(text) > MAX_VALUE:
        raise ValueError(f"«{f.label}» بیش از حد بلند است.")
    if f.kind in ("int", "number"):
        try:
            v = int(text) if f.kind == "int" else float(text)
        except ValueError:
            raise ValueError(f"«{f.label}» باید عدد باشد.") from None
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError(f"«{f.label}» نامعتبر است.")
        if f.min is not None and v < f.min or f.max is not None and v > f.max:
            raise ValueError(f"«{f.label}» باید بین {f.min} و {f.max} باشد.")
        return v
    if f.kind == "date":
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise ValueError(f"«{f.label}» تاریخ معتبر نیست (سال-ماه-روز).") from None
    if f.kind == "choice":
        if text not in {c[0] for c in f.choices}:
            raise ValueError(f"«{f.label}»: گزینه‌ی نامعتبر.")
        return text
    if f.max is not None and len(text) > f.max:
        raise ValueError(f"«{f.label}» حداکثر {int(f.max)} نویسه است.")
    return text


def read_form(form: Form, post) -> tuple[dict, list[str]]:
    values, errors = {}, []
    for f in form.fields:
        try:
            values[f.name] = convert_field(f, post.get(f"f_{f.name}"))
        except ValueError as exc:
            errors.append(str(exc))
    return values, errors


def insert_row(ws, form: Form, values: dict) -> None:
    insert_rows(ws, form, [values])


def _norm_raw(raw):
    """مقدار JSON ← متن برای convert_field؛ ساختار تودرتو پذیرفته نیست."""
    if isinstance(raw, bool):
        return "1" if raw else ""
    if raw is None:
        return ""
    if isinstance(raw, (dict, list)):
        raise ValueError("مقدار تودرتو پذیرفته نمی‌شود.")
    return raw if isinstance(raw, str) else str(raw)


def read_ingest_row(spec: IngestSpec, row) -> dict:
    """یک ردیف دریافتی (dict) ← مقدارهای نوع‌دار طبق فیلدها؛ ValueError با پیام فارسی. فیلد ناشناخته نادیده گرفته می‌شود."""
    if not isinstance(row, dict):
        raise ValueError("هر ردیف باید یک شیء باشد.")
    return {f.name: convert_field(f, _norm_raw(row.get(f.name))) for f in spec.fields}


def _resolve(ws, form, *, need_id: bool = False):
    """جدول و ستون‌های فرم را در کاتالوگ بررسی می‌کند؛ (schema، name، نام ستون‌ها، ستون‌های هندسه، جای‌نگهدار هر ستون)."""
    cat = tenantdb.catalog(ws)
    schema, _, name = form.table.rpartition(".")
    schema = schema or "public"
    if schema.startswith("pg_") or schema == "information_schema" or name in ("spatial_ref_sys", "geometry_columns", "geography_columns"):
        raise SpecError("نوشتن در جدول‌های سیستمی مجاز نیست.")
    table = next((t for t in cat.tables() if t.schema == schema and t.name == name), None)
    if table is None:
        raise SpecError(f"جدول «{form.table}» در این پایگاه داده نیست.")
    if table.kind not in ("r", "p"):
        raise SpecError("فرم فقط روی جدول عادی ثبت می‌کند، نه نما یا جدول خارجی.")
    cols = {c["name"]: c for c in cat.columns(table)}
    if need_id and not (cols.get("id") and cols["id"]["pk"]):
        raise SpecError("ویرایش و حذف ردیف جدولی با کلید اصلی «id» می‌خواهد.")
    for f in form.fields:
        c = cols.get(f.name)
        if c is None:
            raise SpecError(f"ستون «{f.name}» در جدول «{form.table}» نیست.")
        if c["generated"] or c["identity"] == "a":
            raise SpecError(f"ستون «{f.name}» قابل نوشتن از فرم نیست.")
        if f.kind == "geometry":
            want = geomval.PG_TYPES[f.geom].lower()
            have = str(c["type"]).lower().replace(" ", "")
            if not c["spatial"] or have not in ("geometry", f"geometry({want},4326)"):
                raise SpecError(f"ستون «{f.name}» از نوع هندسه‌ی {f.geom} با SRID ۴۳۲۶ نیست.")
        elif c["spatial"]:
            raise SpecError(f"ستون «{f.name}» قابل نوشتن از فرم نیست.")
    names = [f.name for f in form.fields]
    geom_cols = {f.name for f in form.fields if f.kind == "geometry"}
    ph = {n: (sql.SQL("ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)") if n in geom_cols else sql.Placeholder()) for n in names}
    return schema, name, names, geom_cols, ph


def _check_geoms(conn, form, rows: list[dict]) -> None:
    """هندسه‌ها را با PostGIS (ST_IsValid) می‌سنجد؛ SpecError با پیام فارسی."""
    for f in form.fields:
        if f.kind != "geometry":
            continue
        for r in rows:
            if r[f.name] is not None and not conn.execute(
                    "SELECT ST_IsValid(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))", (str(r[f.name]),)).fetchone()[0]:
                raise SpecError(f"«{f.label}»: شکل معتبر نیست (مثلاً ضلع‌ها همدیگر را قطع کرده‌اند).")


def _param(v, name, geom_cols):
    return None if v is None else (str(v) if name in geom_cols else v)


def insert_rows(ws, form, rows: list[dict]) -> None:
    """INSERT یک یا چند ردیف در **یک تراکنش** (همه یا هیچ). `form` هر شیئی با `.table` و `.fields` است (فرم یا IngestSpec).
    یک ردیف با نقش مالک. جدول و ستون‌ها باید در کاتالوگ باشند؛ فقط جدول عادی؛ ستون تولیدشده/identity-always رد می‌شود.

    مقدارها همه پارامتر متصل هستند و نام‌ها با Identifier می‌آیند؛ هیچ متن پلاگینی وارد SQL نمی‌شود.
    SpecError = مشکل در تعریف فرم یا ساختار جدول (پیام فارسی)؛ خطای پایگاه داده به‌صورت استثنا بالا می‌رود.
    """
    schema, name, names, geom_cols, ph = _resolve(ws, form)
    query = sql.SQL("INSERT INTO {rel} ({cols}) VALUES ({vals})").format(
        rel=sql.Identifier(schema, name),
        cols=sql.SQL(", ").join(sql.Identifier(n) for n in names),
        vals=sql.SQL(", ").join(ph[n] for n in names))
    with tenantdb.connect(ws, write=True, as_owner=True) as conn:
        conn.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(f"{TIMEOUT_S}s")))
        _check_geoms(conn, form, rows)
        with conn.cursor() as cur:
            cur.executemany(query, [[_param(r[n], n, geom_cols) for n in names] for r in rows])
        conn.commit()


def replace_rows(ws, spec, rows: list[dict]) -> None:
    """حالت `replace` منبع بیرونی (مثل پیش‌بینی): در **یک تراکنش** ردیف‌های هم‌پوشان (کلید زمانی ≥ کمترین زمان ورودی و همان مقدار ستون‌های
    consts: lat، lon، model…) از همان جدول پاک و ردیف‌های تازه نوشته می‌شود. فقط جدول و ستون‌های اعلام‌شده؛ همه پارامتری."""
    if not rows:
        return
    schema, name, names, geom_cols, ph = _resolve(ws, spec)
    key = spec.cursor
    scope = [c for c, _i in spec.consts]
    lo = min(str(r[key]) for r in rows if r.get(key) is not None)
    where = [sql.SQL("{} >= %s").format(sql.Identifier(key))] + [sql.SQL("{} IS NOT DISTINCT FROM %s").format(sql.Identifier(c)) for c in scope]
    params = [lo] + [rows[0][c] for c in scope]
    insert = sql.SQL("INSERT INTO {rel} ({cols}) VALUES ({vals})").format(
        rel=sql.Identifier(schema, name), cols=sql.SQL(", ").join(sql.Identifier(n) for n in names),
        vals=sql.SQL(", ").join(ph[n] for n in names))
    with tenantdb.connect(ws, write=True, as_owner=True) as conn:
        conn.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(f"{TIMEOUT_S}s")))
        conn.execute(sql.SQL("DELETE FROM {rel} WHERE {w}").format(rel=sql.Identifier(schema, name), w=sql.SQL(" AND ").join(where)), params)
        with conn.cursor() as cur:
            cur.executemany(insert, [[_param(r[n], n, geom_cols) for n in names] for r in rows])
        conn.commit()


# ---------------------------------------------------------------------- ویرایش و حذف ردیف (`[[records]]`)
def fetch_records(ws, rec: RecordSpec) -> tuple[list[str], list[list]]:
    """(سرستون‌ها، ردیف‌ها: [id، مقدارهای ستون‌های نمایشی…])؛ تازه‌ترین‌ها اول. فقط‌خواندنی با نقش مرورگر."""
    schema, name, _n, _g, _p = _resolve(ws, rec, need_id=True)
    cols = [sql.Identifier("id")] + [sql.Identifier(c) for c in rec.columns]
    with tenantdb.connect(ws) as conn:
        conn.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(f"{TIMEOUT_S}s")))
        cur = conn.execute(sql.SQL("SELECT {cols} FROM {rel} ORDER BY id DESC LIMIT {n}").format(
            cols=sql.SQL(", ").join(cols), rel=sql.Identifier(schema, name), n=sql.Literal(rec.limit)))
        return [d.name for d in cur.description], [[_fmt(v) if i else v for i, v in enumerate(r)] for r in cur.fetchall()]


def fetch_record(ws, rec: RecordSpec, rid: int) -> dict | None:
    """مقدارهای قابل‌ویرایش یک ردیف (هندسه به‌صورت GeoJSON)؛ None اگر نیست."""
    schema, name, names, geom_cols, _ph = _resolve(ws, rec, need_id=True)
    cols = [sql.SQL("ST_AsGeoJSON({c})").format(c=sql.Identifier(n)) if n in geom_cols else sql.Identifier(n) for n in names]
    with tenantdb.connect(ws) as conn:
        conn.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(f"{TIMEOUT_S}s")))
        row = conn.execute(sql.SQL("SELECT {cols} FROM {rel} WHERE id = %s").format(
            cols=sql.SQL(", ").join(cols), rel=sql.Identifier(schema, name)), (rid,)).fetchone()
    return None if row is None else dict(zip(names, row, strict=True))


def update_record(ws, rec: RecordSpec, rid: int, values: dict) -> None:
    """UPDATE فقط ستون‌های اعلام‌شده‌ی یک ردیف با شناسه‌ی `id` (پارامتری؛ SpecError اگر ردیف نیست)."""
    schema, name, names, geom_cols, ph = _resolve(ws, rec, need_id=True)
    sets = sql.SQL(", ").join(sql.SQL("{} = {}").format(sql.Identifier(n), ph[n]) for n in names)
    with tenantdb.connect(ws, write=True, as_owner=True) as conn:
        conn.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(f"{TIMEOUT_S}s")))
        _check_geoms(conn, rec, [values])
        cur = conn.execute(sql.SQL("UPDATE {rel} SET {sets} WHERE id = %s").format(rel=sql.Identifier(schema, name), sets=sets),
                           [_param(values[n], n, geom_cols) for n in names] + [rid])
        if cur.rowcount != 1:
            conn.rollback()
            raise SpecError("ردیف پیدا نشد.")
        conn.commit()


def delete_record(ws, rec: RecordSpec, rid: int) -> None:
    schema, name, _n, _g, _p = _resolve(ws, rec, need_id=True)
    with tenantdb.connect(ws, write=True, as_owner=True) as conn:
        conn.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(f"{TIMEOUT_S}s")))
        cur = conn.execute(sql.SQL("DELETE FROM {rel} WHERE id = %s").format(rel=sql.Identifier(schema, name)), (rid,))
        if cur.rowcount != 1:
            conn.rollback()
            raise SpecError("ردیف پیدا نشد.")
        conn.commit()
