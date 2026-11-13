"""پلاگین‌های نمونه‌ی رایگان برای نمایش و آزمودن قابلیت‌های سکو از پنل (docs/plugins/testing-guide.md): بدون سرور و بدون امضای بیرونی.

دو پلاگین **مستقل** و عمومی-رایگان (در بخش رایگان بازار):
- «هواشناسی آنلاین» (`weather_online`): پیش‌بینی ساعتی و تاریخچه از Open-Meteo با انتخاب متغیرها و مدل (قابلیت منابع بیرونی).
- «شناسنامه باغات» (`orchard_registry`): ثبت باغ با کشیدن محدوده، ویرایش/حذف، گزارش PDF (قابلیت‌های ترسیم و گزارش).
با «نصب نمونه‌ها» از «پلاگین‌ها ← ساخت» نصب می‌شوند. این‌ها نمونه‌ی ساخت پلاگین‌اند؛ سازمان یا متخصص می‌تواند پلاگین اختصاصی سفارش دهد.
"""
from __future__ import annotations

from .wizard import toml_dumps

# ---------------------------------------------------------------------- هواشناسی آنلاین
WEATHER_ID = "weather_online"
WEATHER_KEY = "meteo"
# (نام متغیر ساعتی Open-Meteo، برچسب فارسی)
WEATHER_VARS = [
    ("temperature_2m", "دمای هوا (°C)"), ("apparent_temperature", "دمای احساسی (°C)"), ("relative_humidity_2m", "رطوبت نسبی (٪)"),
    ("dew_point_2m", "نقطه‌ی شبنم (°C)"), ("precipitation", "بارش کل (mm)"), ("rain", "باران (mm)"), ("snowfall", "برف (cm)"),
    ("pressure_msl", "فشار تراز دریا (hPa)"), ("surface_pressure", "فشار سطح (hPa)"), ("cloud_cover", "پوشش ابر (٪)"),
    ("wind_speed_10m", "سرعت باد ۱۰ متری (km/h)"), ("wind_direction_10m", "جهت باد (°)"), ("wind_gusts_10m", "تندباد (km/h)"),
    ("shortwave_radiation", "تابش کوتاه‌موج (W/m²)"), ("uv_index", "شاخص UV"), ("visibility", "دید افقی (m)"),
    ("et0_fao_evapotranspiration", "تبخیر-تعرق مرجع ET0 (mm)"), ("vapour_pressure_deficit", "کمبود فشار بخار (kPa)"),
    ("soil_temperature_0cm", "دمای خاک سطح (°C)"), ("soil_moisture_0_to_1cm", "رطوبت خاک ۰ تا ۱ سانتی‌متر (m³/m³)"),
]
DEFAULT_VARS = "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_direction_10m"
# مدل‌های هواشناسی Open-Meteo (فهرست مستندات؛ ابتدا مدل‌های جهانی که ایران را پوشش می‌دهند)
WEATHER_MODELS = [
    ("best_match", "بهترین ترکیب (پیش‌فرض Open-Meteo)"), ("ecmwf_ifs025", "ECMWF IFS ۰٫۲۵°"), ("ecmwf_aifs025_single", "ECMWF AIFS (هوش مصنوعی)"),
    ("gfs_seamless", "NOAA GFS یکپارچه"), ("gfs_global", "NOAA GFS جهانی"), ("gfs_graphcast025", "NOAA GraphCast (هوش مصنوعی)"),
    ("icon_seamless", "DWD ICON یکپارچه"), ("icon_global", "DWD ICON جهانی"), ("icon_eu", "DWD ICON اروپا"), ("icon_d2", "DWD ICON-D2 (آلمان)"),
    ("gem_seamless", "کانادا GEM یکپارچه"), ("gem_global", "کانادا GEM جهانی"), ("gem_regional", "کانادا GEM منطقه‌ای"),
    ("meteofrance_seamless", "Météo-France یکپارچه"), ("meteofrance_arpege_world", "Météo-France ARPEGE جهانی"),
    ("meteofrance_arpege_europe", "Météo-France ARPEGE اروپا"), ("meteofrance_arome_france", "Météo-France AROME (فرانسه)"),
    ("jma_seamless", "ژاپن JMA یکپارچه"), ("jma_gsm", "ژاپن JMA GSM جهانی"), ("jma_msm", "ژاپن JMA MSM"),
    ("ukmo_seamless", "بریتانیا UKMO یکپارچه"), ("ukmo_global_deterministic_10km", "بریتانیا UKMO جهانی ۱۰km"),
    ("ukmo_uk_deterministic_2km", "بریتانیا UKMO ۲km"), ("cma_grapes_global", "چین CMA GRAPES جهانی"),
    ("bom_access_global", "استرالیا BOM ACCESS جهانی"), ("metno_seamless", "نروژ MET یکپارچه"), ("metno_nordic", "نروژ MET شمال اروپا"),
    ("knmi_seamless", "هلند KNMI یکپارچه"), ("dmi_seamless", "دانمارک DMI یکپارچه"), ("italia_meteo_arpae_icon_2i", "ایتالیا ICON-2I"),
]
FORECAST_DAYS = [["1", "۱ روز"], ["3", "۳ روز"], ["7", "۷ روز"], ["10", "۱۰ روز"], ["16", "۱۶ روز"]]
LEGAL = ("نکته‌ی مجوز: نشانی رایگان Open-Meteo برای استفاده‌ی غیرتجاری است؛ برای استفاده‌ی تجاری باید اشتراک تجاری یا سرور اختصاصی Open-Meteo داشته باشید.")


def _weather_columns() -> list[dict]:
    cols = [{"name": "t", "type": "text", "required": True}, {"name": "lat", "type": "double"}, {"name": "lon", "type": "double"}, {"name": "model", "type": "text"}]
    return cols + [{"name": v, "type": "double"} for v, _l in WEATHER_VARS]


def _weather_fields() -> list[dict]:
    f = [{"name": "t", "kind": "text", "label": "زمان", "required": True, "path": "time", "max": 20},
         {"name": "lat", "kind": "number", "label": "عرض", "input": "lat"}, {"name": "lon", "kind": "number", "label": "طول", "input": "lon"},
         {"name": "model", "kind": "text", "label": "مدل", "input": "model", "max": 60}]
    return f + [{"name": v, "kind": "number", "label": lbl, "path": v, "optional": True} for v, lbl in WEATHER_VARS]


def _weather_inputs(*, model: bool, days: bool) -> list[dict]:
    ins = [{"name": "lat", "label": "عرض جغرافیایی", "default": "35.7", "min": -90, "max": 90},
           {"name": "lon", "label": "طول جغرافیایی", "default": "51.4", "min": -180, "max": 180},
           {"name": "variables", "label": "متغیرها", "kind": "multi", "default": DEFAULT_VARS, "choices": [[v, lbl] for v, lbl in WEATHER_VARS]}]
    if model:
        ins.append({"name": "model", "label": "مدل هواشناسی", "kind": "choice", "default": "best_match", "choices": [[m, lbl] for m, lbl in WEATHER_MODELS]})
    if days:
        ins.append({"name": "days", "label": "روزهای پیش‌بینی", "kind": "choice", "default": "7", "choices": FORECAST_DAYS})
    return ins


def weather_page() -> dict:
    sel = ", ".join(v for v in ("temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m", "wind_direction_10m", "pressure_msl", "cloud_cover"))
    now_t = "to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD\"T\"HH24:MI')"
    return {
        "key": WEATHER_KEY, "title": "هواشناسی آنلاین", "subtitle": "پیش‌بینی ساعتی و تاریخچه از Open-Meteo؛ ۲۰ متغیر و ۳۰ مدل", "icon": "cloud", "group": "data", "need": "editor",
        "blocks": [
            {"kind": "text", "title": "راهنما", "text": "۱) در کارت «پیش‌بینی» مختصات، متغیرها، مدل و روزها را انتخاب کنید و «ذخیره و فعال‌سازی» را بزنید؛ بعد «دریافت همین حالا». "
                                                       "۲) کارت «تاریخچه» داده‌ی گذشته را (با تأخیر چند روز) اضافه می‌کند. ۳) گزارش PDF و چیدمان بالای صفحه است.\n\n" + LEGAL},
            {"kind": "kpi", "title": "دمای هوا (°C)", "unit": "°C", "sql": f"SELECT temperature_2m FROM weather_online_forecast WHERE t <= {now_t} AND temperature_2m IS NOT NULL ORDER BY t DESC LIMIT 1"},
            {"kind": "kpi", "title": "سرعت باد (km/h)", "sql": f"SELECT wind_speed_10m FROM weather_online_forecast WHERE t <= {now_t} AND wind_speed_10m IS NOT NULL ORDER BY t DESC LIMIT 1"},
            {"kind": "kpi", "title": "رطوبت نسبی (٪)", "sql": f"SELECT relative_humidity_2m FROM weather_online_forecast WHERE t <= {now_t} AND relative_humidity_2m IS NOT NULL ORDER BY t DESC LIMIT 1"},
            {"kind": "table", "title": "پیش‌بینی ساعتی (۴۸ ساعت آینده)", "sql": f"SELECT {sel}, t, model FROM weather_online_forecast WHERE t >= {now_t} ORDER BY t LIMIT 48",
             "columns": [["t", "زمان (UTC)"], ["model", "مدل"], ["temperature_2m", "دما"], ["relative_humidity_2m", "رطوبت"], ["precipitation", "بارش"], ["wind_speed_10m", "باد"],
                         ["wind_direction_10m", "جهت باد"], ["pressure_msl", "فشار"], ["cloud_cover", "ابر"]]},
            {"kind": "bars", "title": "بارش روزانه‌ی پیش‌بینی (mm)", "sql": "SELECT left(t, 10) AS label, round(coalesce(sum(precipitation), 0)::numeric, 1) AS value FROM weather_online_forecast GROUP BY 1 ORDER BY 1 LIMIT 16"},
            {"kind": "table", "title": "تاریخچه (آخرین ۴۸ ساعت ذخیره‌شده)", "sql": "SELECT t, temperature_2m, relative_humidity_2m, precipitation, wind_speed_10m FROM weather_online_history ORDER BY t DESC LIMIT 48",
             "columns": [["t", "زمان (UTC)"], ["temperature_2m", "دما"], ["relative_humidity_2m", "رطوبت"], ["precipitation", "بارش"], ["wind_speed_10m", "باد"]]},
        ],
        "tables": [{"name": "weather_online_forecast", "columns": _weather_columns(), "indexes": [["t"]]},
                   {"name": "weather_online_history", "columns": _weather_columns(), "indexes": [["t"]]}],
        "sources": [
            {"key": "forecast", "title": "پیش‌بینی (Open-Meteo)", "hint": "اول در پنل مدیریت سوئیچ «منابع بیرونی» را روشن و api.open-meteo.com را به میزبان‌های مجاز بیفزایید. برای استفاده‌ی تجاری اشتراک Open-Meteo لازم است.",
             "url": "https://api.open-meteo.com/v1/forecast", "table": "weather_online_forecast", "layout": "columns", "rows_path": "hourly", "cursor": "t", "mode": "replace",
             "every_minutes": 180, "since_days": 1,
             "query": {"latitude": "{lat}", "longitude": "{lon}", "hourly": "{variables}", "models": "{model}", "forecast_days": "{days}", "past_days": "1", "timezone": "UTC"},
             "inputs": _weather_inputs(model=True, days=True), "fields": _weather_fields()},
            {"key": "history", "title": "تاریخچه (Open-Meteo Archive)", "hint": "میزبان archive-api.open-meteo.com را هم در پنل تأیید کنید؛ داده با چند روز تأخیر می‌رسد.",
             "url": "https://archive-api.open-meteo.com/v1/archive", "table": "weather_online_history", "layout": "columns", "rows_path": "hourly", "cursor": "t", "mode": "append",
             "every_minutes": 1440, "since_days": 30,
             "query": {"latitude": "{lat}", "longitude": "{lon}", "hourly": "{variables}", "start_date": "{since}", "end_date": "{today}", "timezone": "UTC"},
             "inputs": _weather_inputs(model=False, days=False),
             "fields": [f for f in _weather_fields() if f["name"] != "model"]},
        ],
        "reports": [{"key": "rep", "title": "گزارش هواشناسی", "subtitle": "وضعیت فعلی، پیش‌بینی و بارش", "blocks": [2, 3, 4, 5, 6]}],
    }


# ---------------------------------------------------------------------- شناسنامه باغات
ORCHARD_ID = "orchard_registry"
ORCHARD_KEY = "registry"
CROPS = [["pistachio", "پسته"], ["pomegranate", "انار"], ["apple", "سیب"], ["walnut", "گردو"], ["almond", "بادام"], ["grape", "انگور"],
         ["citrus", "مرکبات"], ["date", "خرما"], ["olive", "زیتون"], ["peach", "هلو و شلیل"], ["cherry", "گیلاس و آلبالو"], ["other", "سایر"]]
IRRIGATION = [["drip", "قطره‌ای"], ["sprinkler", "بارانی"], ["flood", "غرقابی/سنتی"], ["rainfed", "دیم"]]
WATER = [["well", "چاه"], ["qanat", "قنات"], ["river", "رودخانه/چشمه"], ["network", "شبکه‌ی آبیاری"], ["other", "سایر"]]


def _orchard_fields(with_area: bool) -> list[dict]:
    f = [{"name": "name", "kind": "text", "label": "نام باغ", "required": True, "max": 80},
         {"name": "owner", "kind": "text", "label": "نام مالک/بهره‌بردار", "max": 80},
         {"name": "code", "kind": "text", "label": "کد یا پلاک ثبتی", "max": 40},
         {"name": "crop", "kind": "choice", "label": "محصول اصلی", "choices": CROPS},
         {"name": "variety", "kind": "text", "label": "رقم", "max": 60},
         {"name": "planting_year", "kind": "int", "label": "سال کاشت (میلادی)", "min": 1900, "max": 2100},
         {"name": "tree_count", "kind": "int", "label": "تعداد درخت", "min": 0, "max": 10_000_000},
         {"name": "irrigation", "kind": "choice", "label": "نوع آبیاری", "choices": IRRIGATION},
         {"name": "water_source", "kind": "choice", "label": "منبع آب", "choices": WATER},
         {"name": "soil", "kind": "text", "label": "بافت خاک", "max": 60},
         {"name": "notes", "kind": "text", "label": "یادداشت", "max": 500}]
    if with_area:
        f.append({"name": "area", "kind": "geometry", "geom": "polygon", "label": "محدوده‌ی باغ روی نقشه", "required": True})
    return f


def orchard_page() -> dict:
    t = "orchard_registry_orchards"
    ha = "round((ST_Area(area::geography) / 10000)::numeric, 2)"
    return {
        "key": ORCHARD_KEY, "title": "شناسنامه باغات", "subtitle": "ثبت مشخصات هر باغ و کشیدن محدوده روی نقشه؛ گزارش PDF شناسنامه", "icon": "layers", "group": "data", "need": "editor",
        "blocks": [
            {"kind": "text", "title": "راهنما", "text": "با فرم «ثبت باغ» مشخصات و محدوده‌ی باغ را ثبت کنید؛ مساحت از روی محدوده‌ی کشیده‌شده محاسبه می‌شود. "
                                                       "ویرایش و حذف در فهرست پایین، و گزارش PDF و چیدمان بالای صفحه است."},
            {"kind": "kpi", "title": "تعداد باغ‌ها", "sql": f"SELECT count(*) FROM {t}"},
            {"kind": "kpi", "title": "مساحت کل (هکتار)", "sql": f"SELECT coalesce(round((sum(ST_Area(area::geography)) / 10000)::numeric, 2), 0) FROM {t} WHERE area IS NOT NULL"},
            {"kind": "kpi", "title": "تعداد درخت", "sql": f"SELECT coalesce(sum(tree_count), 0) FROM {t}"},
            {"kind": "table", "title": "فهرست باغ‌ها",
             "sql": f"SELECT id, name, owner, crop, variety, planting_year, tree_count, irrigation, CASE WHEN area IS NULL THEN NULL ELSE {ha} END AS area_ha FROM {t} ORDER BY id DESC LIMIT 200",
             "columns": [["name", "باغ"], ["owner", "مالک"], ["crop", "محصول"], ["variety", "رقم"], ["planting_year", "سال کاشت"], ["tree_count", "درخت"],
                         ["irrigation", "آبیاری"], ["area_ha", "مساحت (هکتار)"]]},
            {"kind": "bars", "title": "مساحت به تفکیک محصول (هکتار)", "sql": f"SELECT coalesce(crop, 'نامشخص') AS label, round((sum(ST_Area(area::geography)) / 10000)::numeric, 2) AS value FROM {t} WHERE area IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 20"},
            {"kind": "map", "title": "نقشه‌ی باغ‌ها", "sql": f"SELECT name, crop, area AS geom FROM {t} WHERE area IS NOT NULL"},
        ],
        "tables": [{"name": t, "columns": [{"name": "name", "type": "text", "required": True}, {"name": "owner", "type": "text"}, {"name": "code", "type": "text"},
                                           {"name": "crop", "type": "text"}, {"name": "variety", "type": "text"}, {"name": "planting_year", "type": "integer"},
                                           {"name": "tree_count", "type": "integer"}, {"name": "irrigation", "type": "text"}, {"name": "water_source", "type": "text"},
                                           {"name": "soil", "type": "text"}, {"name": "notes", "type": "text"}, {"name": "area", "type": "polygon"},
                                           {"name": "created_at", "type": "timestamptz", "auto_now": True}]}],
        "forms": [{"key": "add", "title": "ثبت باغ", "table": t, "submit": "ثبت باغ", "fields": _orchard_fields(True)}],
        "records": [{"key": "edit", "title": "ویرایش و حذف باغ‌ها", "table": t, "columns": ["name", "owner", "crop", "tree_count"], "fields": _orchard_fields(True)}],
        "reports": [{"key": "cert", "title": "شناسنامه‌ی باغات", "subtitle": "مشخصات، مساحت و نقشه", "blocks": [2, 3, 4, 5, 6, 7]}],
    }


# ---------------------------------------------------------------------- نصب
SAMPLES = {
    WEATHER_ID: {"name": "هواشناسی آنلاین (Open-Meteo)", "page": (WEATHER_KEY, weather_page),
                 "readme": "دریافت آنلاین هواشناسی از Open-Meteo: ۲۰ متغیر ساعتی، ۳۰ مدل، پیش‌بینی و تاریخچه، جدول و گزارش PDF. نمونه‌ی رایگان.",
                 "summary": "پیش‌بینی و تاریخچه‌ی ساعتی هواشناسی با انتخاب متغیر و مدل"},
    ORCHARD_ID: {"name": "شناسنامه باغات", "page": (ORCHARD_KEY, orchard_page),
                 "readme": "ثبت شناسنامه‌ی باغ (محصول، رقم، آبیاری، مساحت از روی محدوده‌ی نقشه)، ویرایش و حذف و گزارش PDF. نمونه‌ی رایگان.",
                 "summary": "شناسنامه‌ی باغات با محدوده‌ی نقشه و گزارش PDF"},
}


def page_text(plugin_id: str) -> str:
    return toml_dumps(SAMPLES[plugin_id]["page"][1]())


def ensure_draft(user, plugin_id: str):
    """پیش‌نویس نمونه را می‌سازد یا به‌روز می‌کند و برمی‌گرداند."""
    from .models import PluginDraft

    spec = SAMPLES[plugin_id]
    d, _ = PluginDraft.objects.get_or_create(plugin_id=plugin_id, defaults={"name": spec["name"], "kind": "feature"})
    d.name, d.kind, d.readme = spec["name"], "feature", spec["readme"]
    d.pages = {spec["page"][0]: page_text(plugin_id)}
    d.code, d.alerts, d.tests, d.wizard = {}, {}, {}, {}
    d.updated_by = user
    d.save()
    return d


def install(user, plugin_id: str | None = None) -> list[dict]:
    """ساخت و انتشار نمونه‌ها (عمومی رایگان)؛ فهرست {id، active، message}. PublishError با پیام فارسی."""
    from . import publish

    out = []
    for pid in ([plugin_id] if plugin_id else list(SAMPLES)):
        d = ensure_draft(user, pid)
        res = publish.publish(d, user, {"mode": "public_free"})
        out.append({"id": pid, "name": SAMPLES[pid]["name"], "active": res["active"], "message": res["message"]})
    return out
