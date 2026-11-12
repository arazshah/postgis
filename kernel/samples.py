"""پلاگین نمونه‌ی «آزمایشگاه» برای آزمودن قابلیت‌های تازه از پنل (docs/plugins/testing-guide.md): بدون سرور و بدون امضای بیرونی.

یک صفحه با جدول مزرعه (چندضلعی)، فرم با ترسیم روی نقشه، ویرایش/حذف ردیف، منبع بیرونی هواشناسی (Open-Meteo) و گزارش PDF.
با «ساخت و انتشار نمونه» از صفحه‌ی «پلاگین‌ها ← ساخت» نصب می‌شود (عمومی رایگان، پس هر پایگاهی صفحه‌اش را می‌بیند).
"""
from __future__ import annotations

PLUGIN_ID = "demolab"
PAGE_KEY = "lab"

PAGE = """key = "lab"
title = "آزمایشگاه ژئوپایگاه"
subtitle = "نمونه‌ی آزمون چندضلعی، ویرایش ردیف، منبع بیرونی هواشناسی و گزارش PDF"
icon = "chart"
group = "data"
need = "editor"

[[blocks]]
kind = "text"
title = "راهنمای این صفحه"
text = "دکمه‌های «گزارش PDF»، «تصویر» و «چیدمان» بالای همین صفحه، کنار عنوان هستند. فرم ثبت مزرعه، فهرست ویرایش و حذف، و کارت «دمای ساعتی از Open-Meteo» در پایین صفحه‌اند. در کارت دما اول «ذخیره و فعال‌سازی» را بزنید؛ بعد دکمه‌ی «دریافت همین حالا» ظاهر می‌شود."

[[blocks]]
kind = "kpi"
title = "تعداد مزرعه‌ها"
sql = "SELECT count(*) FROM demolab_farms"

[[blocks]]
kind = "table"
title = "مزرعه‌ها"
sql = "SELECT id, name, crop FROM demolab_farms ORDER BY id DESC LIMIT 100"

[[blocks]]
kind = "map"
title = "نقشه‌ی مزرعه‌ها"
sql = "SELECT name, crop, area AS geom FROM demolab_farms WHERE area IS NOT NULL"

[[blocks]]
kind = "table"
title = "دمای ساعتی (از منبع بیرونی)"
sql = "SELECT t AS ساعت, temp AS دما FROM demolab_weather ORDER BY t DESC LIMIT 24"

[[tables]]
name = "demolab_farms"

[[tables.columns]]
name = "name"
type = "text"
required = true

[[tables.columns]]
name = "crop"
type = "text"

[[tables.columns]]
name = "area"
type = "polygon"

[[tables]]
name = "demolab_weather"

[[tables.columns]]
name = "t"
type = "text"

[[tables.columns]]
name = "temp"
type = "double"

[[forms]]
key = "add_farm"
title = "ثبت مزرعه (با کشیدن محدوده روی نقشه)"
table = "demolab_farms"
submit = "ثبت مزرعه"

[[forms.fields]]
name = "name"
kind = "text"
label = "نام مزرعه"
required = true
max = 60

[[forms.fields]]
name = "crop"
kind = "choice"
label = "محصول"
choices = [["wheat", "گندم"], ["corn", "ذرت"], ["rice", "برنج"]]

[[forms.fields]]
name = "area"
kind = "geometry"
geom = "polygon"
label = "محدوده"
required = true

[[records]]
key = "farms"
title = "ویرایش و حذف مزرعه‌ها"
table = "demolab_farms"
columns = ["name", "crop"]

[[records.fields]]
name = "name"
kind = "text"
label = "نام مزرعه"
required = true
max = 60

[[records.fields]]
name = "crop"
kind = "choice"
label = "محصول"
choices = [["wheat", "گندم"], ["corn", "ذرت"], ["rice", "برنج"]]

[[records.fields]]
name = "area"
kind = "geometry"
geom = "polygon"
label = "محدوده"

[[sources]]
key = "weather"
title = "دمای ساعتی از Open-Meteo"
hint = "اول در پنل مدیریت سوئیچ «منابع بیرونی» را روشن و api.open-meteo.com را به میزبان‌های مجاز بیفزایید."
url = "https://api.open-meteo.com/v1/forecast"
table = "demolab_weather"
layout = "columns"
rows_path = "hourly"
cursor = "t"
every_minutes = 60
since_days = 1
query = { latitude = "{lat}", longitude = "{lon}", hourly = "temperature_2m", start_date = "{since}", end_date = "{today}", timezone = "UTC" }

[[sources.inputs]]
name = "lat"
label = "عرض جغرافیایی"
default = "35.7"
min = -90
max = 90

[[sources.inputs]]
name = "lon"
label = "طول جغرافیایی"
default = "51.4"
min = -180
max = 180

[[sources.fields]]
name = "t"
kind = "text"
label = "زمان"
required = true
path = "time"
max = 20

[[sources.fields]]
name = "temp"
kind = "number"
label = "دما"
path = "temperature_2m"

[[reports]]
key = "rep"
title = "گزارش آزمایشگاه"
subtitle = "مزرعه‌ها و دمای اخیر"
blocks = [2, 3, 4, 5]
"""

README = "پلاگین نمونه‌ی آزمون قابلیت‌های تازه‌ی ژئوپایگاه (چندضلعی، ویرایش ردیف، منبع بیرونی، گزارش PDF). فقط برای آزمایش است."


def ensure_draft(user):
    """پیش‌نویس نمونه را می‌سازد یا به‌روز می‌کند و برمی‌گرداند."""
    from .models import PluginDraft

    d, _ = PluginDraft.objects.get_or_create(plugin_id=PLUGIN_ID, defaults={"name": "آزمایشگاه ژئوپایگاه", "kind": "feature"})
    d.name, d.kind, d.readme = "آزمایشگاه ژئوپایگاه", "feature", README
    d.pages = {PAGE_KEY: PAGE}
    d.code, d.alerts, d.tests, d.wizard = {}, {}, {}, {}
    d.updated_by = user
    d.save()
    return d


def install(user) -> dict:
    """ساخت و انتشار نمونه (عمومی رایگان)؛ برمی‌گرداند نتیجه‌ی publish.publish. PublishError با پیام فارسی."""
    from . import publish

    d = ensure_draft(user)
    return publish.publish(d, user, {"mode": "public_free"})
