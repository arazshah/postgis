"""دستورهای آماده‌ی ساخت پلاگین (docs/adr/0010، مرحله‌ی ۱۱): نقشه‌ی کامل و معتبر با یک کلیک؛ بعد هر چیزی را در استودیو عوض می‌کنید.

هر دستور تابعی است که با شناسه‌ی پلاگین (پیشوند جدول‌ها) نقشه‌ی کامل می‌سازد؛ نقشه از همان عملیات `kernel.blueprint` می‌گذرد، پس هر دستور
از اعتبارسنجی و کامپایل و فهرست کیفیت می‌گذرد (آزمون دارد). دسترسی و قیمت عمداً خالی است تا سازنده انتخاب کند.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from . import blueprint


@dataclass(frozen=True)
class Recipe:
    key: str
    title: str
    hint: str
    icon: str
    parts: tuple[str, ...]
    summary: str
    build: Callable[[str], dict]


def _col(name, type_, label, **kw):
    return {"name": name, "type": type_, "label": label, **kw}


def _base(pid: str, summary: str, icon: str) -> dict:
    return {"intro": {"summary": summary, "icon": icon}, "tables": [], "pages": [], "code": {}}


def _apply(pid: str, spec: dict, *ops: dict) -> dict:
    return blueprint.apply_all(spec, pid, list(ops)) if ops else spec


def blank(pid: str) -> dict:
    return _base(pid, "", "chart")


def fleet(pid: str) -> dict:
    t = f"{pid}_points"
    s = _base(pid, "پایش زنده‌ی دستگاه‌ها روی نقشه با آخرین موقعیت، سرعت و دریافت داده از دستگاه با توکن.", "pulse")
    table = {"name": t, "columns": [_col("device", "text", "دستگاه", required=True), _col("lat", "double", "عرض", min=-90, max=90, required=True),
                                    _col("lon", "double", "طول", min=-180, max=180, required=True), _col("speed", "double", "سرعت (km/h)", min=0, max=400),
                                    _col("at", "timestamptz", "زمان", auto_now=True)], "indexes": [["device", "at"]]}
    return _apply(pid, s, {"op": "table.add", "table": table}, {"op": "page.add", "title": "پایش آنلاین", "subtitle": "آخرین موقعیت دستگاه‌ها", "icon": "pulse", "refresh": 15,
        "need": "editor", "blocks": [
            {"kind": "kpi", "title": "دستگاه فعال (۵ دقیقه‌ی اخیر)", "table": t, "agg": "count", "distinct": "device", "since_col": "at", "since_minutes": 5, "unit": "دستگاه"},
            {"kind": "kpi", "title": "میانگین سرعت", "table": t, "agg": "avg", "column": "speed", "since_col": "at", "since_minutes": 60, "unit": "km/h"},
            {"kind": "kpi", "title": "ثبت‌های امروز", "table": t, "agg": "count", "since_col": "at", "since_minutes": 1440},
            {"kind": "map", "title": "آخرین موقعیت", "table": t, "lat": "lat", "lon": "lon", "props": ["device", "speed"], "latest_by": "device", "time_col": "at"},
            {"kind": "bars", "title": "ثبت هر دستگاه", "table": t, "label": "device", "agg": "count", "since_col": "at", "since_minutes": 1440},
            {"kind": "table", "title": "آخرین ثبت‌ها", "table": t, "columns": ["device", "speed", "at"], "order_by": "at", "limit": 20},
            {"kind": "ingest", "title": "دریافت از دستگاه", "table": t, "fields": ["device", "lat", "lon", "speed"], "key": "gps", "hint": "دستگاه با توکن هر پایگاه JSON می‌فرستد."},
            {"kind": "report", "title": "گزارش پایش", "key": "report", "blocks": [], "button": "گزارش PDF"}]})


def field(pid: str) -> dict:
    t = f"{pid}_obs"
    s = _base(pid, "ثبت میدانی مشاهده‌ها با موقعیت روی نقشه، فهرست قابل‌ویرایش و گزارش PDF.", "pin")
    table = {"name": t, "columns": [_col("title", "text", "عنوان", required=True), _col("kind", "text", "نوع", choices=[["good", "سالم"], ["warn", "نیازمند بررسی"], ["bad", "خراب"]]),
                                    _col("note", "text", "یادداشت"), _col("place", "point", "موقعیت"), _col("at", "timestamptz", "زمان ثبت", auto_now=True)], "indexes": [["at"]]}
    return _apply(pid, s, {"op": "table.add", "table": table},
        {"op": "page.add", "title": "ثبت مشاهده", "subtitle": "مشاهده‌ی تازه را با موقعیتش ثبت کنید", "icon": "pin", "need": "editor", "blocks": [
            {"kind": "text", "title": "راهنما", "text": "عنوان و نوع را بنویسید و موقعیت را روی نقشه بزنید."},
            {"kind": "form", "title": "مشاهده‌ی تازه", "table": t, "key": "obs", "fields": ["title", "kind", "note", "place"], "submit": "ثبت مشاهده"}]},
        {"op": "page.add", "title": "فهرست و نقشه", "subtitle": "همه‌ی مشاهده‌ها", "icon": "table", "need": "editor", "refresh": 60, "blocks": [
            {"kind": "kpi", "title": "کل مشاهده‌ها", "table": t, "agg": "count"},
            {"kind": "bars", "title": "بر پایه‌ی نوع", "table": t, "label": "kind", "agg": "count"},
            {"kind": "map", "title": "نقشه‌ی مشاهده‌ها", "table": t, "point": "place", "props": ["title", "kind"]},
            {"kind": "records", "title": "ویرایش و حذف", "table": t, "key": "edit", "columns": ["title", "kind", "at"], "fields": ["title", "kind", "note"]},
            {"kind": "report", "title": "گزارش مشاهده‌ها", "key": "report", "blocks": [], "button": "گزارش PDF"}]})


def periodic(pid: str) -> dict:
    t = f"{pid}_items"
    s = _base(pid, "ثبت و گزارش دوره‌ای شاخص‌ها با فیلتر بازه‌ی زمانی و خروجی PDF.", "chart")
    table = {"name": t, "columns": [_col("name", "text", "شاخص", required=True), _col("value", "double", "مقدار", required=True), _col("day", "date", "تاریخ", required=True)],
             "indexes": [["day"]]}
    rng = {"name": "range", "kind": "choice", "label": "بازه", "default": "10080", "choices": [["1440", "یک روز"], ["10080", "یک هفته"], ["43200", "یک ماه"]]}
    return _apply(pid, s, {"op": "table.add", "table": table}, {"op": "page.add", "title": "گزارش دوره‌ای", "subtitle": "شاخص‌ها در بازه‌ی انتخابی", "icon": "chart", "need": "editor",
        "params": [rng], "blocks": [
            {"kind": "kpi", "title": "تعداد ثبت", "table": t, "agg": "count", "since_col": "day", "since_param": "range"},
            {"kind": "kpi", "title": "میانگین مقدار", "table": t, "agg": "avg", "column": "value", "since_col": "day", "since_param": "range"},
            {"kind": "bars", "title": "میانگین هر شاخص", "table": t, "label": "name", "agg": "avg", "column": "value", "since_col": "day", "since_param": "range"},
            {"kind": "table", "title": "ثبت‌های اخیر", "table": t, "columns": ["name", "value", "day"], "order_by": "day", "limit": 30, "since_col": "day", "since_param": "range"},
            {"kind": "form", "title": "ثبت مقدار", "table": t, "key": "entry", "submit": "ثبت"},
            {"kind": "report", "title": "گزارش دوره‌ای", "key": "weekly", "blocks": [], "button": "گزارش PDF", "landscape": True}]})


def weather(pid: str) -> dict:
    t = f"{pid}_daily"
    s = _base(pid, "پیش‌بینی روزانه‌ی دما و بارش از Open-Meteo برای مختصات هر پایگاه، با جدول و نمودار.", "cloud")
    table = {"name": t, "columns": [_col("day", "date", "روز"), _col("tmax", "double", "بیشینه‌ی دما (°C)"), _col("tmin", "double", "کمینه‌ی دما (°C)"), _col("rain", "double", "بارش (mm)")]}
    src = {"kind": "source", "title": "پیش‌بینی روزانه (Open-Meteo)", "key": "daily", "table": t, "url": "https://api.open-meteo.com/v1/forecast", "layout": "columns", "rows_path": "daily",
           "every_minutes": 180, "since_days": 2, "query": [["latitude", "{lat}"], ["longitude", "{lon}"], ["daily", "temperature_2m_max,temperature_2m_min,precipitation_sum"], ["timezone", "auto"]],
           "map": [{"column": "day", "path": "time"}, {"column": "tmax", "path": "temperature_2m_max"}, {"column": "tmin", "path": "temperature_2m_min"}, {"column": "rain", "path": "precipitation_sum"}],
           "inputs": [{"name": "lat", "label": "عرض جغرافیایی", "kind": "number", "default": "35.7", "min": -90, "max": 90}, {"name": "lon", "label": "طول جغرافیایی", "kind": "number", "default": "51.4", "min": -180, "max": 180}],
           "hint": "میزبان api.open-meteo.com باید در پنل (منابع بیرونی) تأیید شود."}
    return _apply(pid, s, {"op": "table.add", "table": table}, {"op": "page.add", "title": "هواشناسی", "subtitle": "پیش‌بینی روزانه", "icon": "cloud", "need": "editor", "blocks": [
        {"kind": "text", "title": "راهنما", "text": "مختصات را در کارت «پیش‌بینی روزانه» تنظیم و «حالا واکشی کن» را بزنید؛ بعد داده‌ها خودکار به‌روز می‌شوند."},
        {"kind": "kpi", "title": "بیشینه‌ی دمای امروز", "table": t, "agg": "max", "column": "tmax", "unit": "°C"},
        {"kind": "kpi", "title": "مجموع بارش", "table": t, "agg": "sum", "column": "rain", "unit": "mm"},
        {"kind": "bars", "title": "بارش هر روز", "table": t, "label": "day", "agg": "sum", "column": "rain"},
        {"kind": "table", "title": "جدول پیش‌بینی", "table": t, "columns": ["day", "tmax", "tmin", "rain"], "order_by": "day", "limit": 16},
        src]})


RECIPES = (
    Recipe("blank", "پلاگین خالی", "از صفر شروع می‌کنید؛ جدول و صفحه را خودتان می‌سازید.", "plus", (), "", blank),
    Recipe("fleet", "پایش ناوگان", "نقشه‌ی آخرین موقعیت، شمارنده‌ها، نمودار و دریافت داده از دستگاه با توکن.", "pulse", ("نقشه", "شمارنده", "دریافت از دستگاه", "گزارش PDF"), "", fleet),
    Recipe("field", "ثبت میدانی", "فرم ثبت با موقعیت، فهرست قابل‌ویرایش، نقشه و گزارش.", "pin", ("فرم", "ویرایش ردیف", "نقشه", "گزارش PDF"), "", field),
    Recipe("periodic", "گزارش دوره‌ای", "ثبت شاخص‌ها، فیلتر بازه‌ی زمانی، نمودار و گزارش PDF افقی.", "chart", ("فیلتر بازه", "فرم", "نمودار", "گزارش PDF"), "", periodic),
    Recipe("weather", "هواشناسی از API", "واکشی دوره‌ای پیش‌بینی از Open-Meteo با ورودی مختصات و نمودار بارش.", "cloud", ("منبع بیرونی", "نمودار", "جدول"), "", weather),
)
BY_KEY = {r.key: r for r in RECIPES}


def build(key: str, plugin_id: str) -> dict:
    """نقشه‌ی دستور `key` برای پلاگین `plugin_id`؛ KeyError اگر دستور نیست."""
    return blueprint.ensure_ids(BY_KEY[key].build(plugin_id))
