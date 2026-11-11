# سطح ۲: کد ایزوله (بسته‌ی دارای پایتون)

مرجع: `docs/adr/0002-plugin-platform.md` و `docs/adr/0004`. برای منطق محاسباتی که با SQL و صفحه‌ی اعلانی نمی‌شود. **سطح ۳ (جنگو در پردازه) هنوز نیست.**

## قالب بسته
مثل `docs/plugins/packages.md` ولی `tier = 2` و پوشه‌ی `code/`:
```
plugin.toml           # tier = 2؛ [contributes] handlers = ["stats"]
pages/live.toml       # بلوک kpi|table|bars با handler = "stats" به‌جای sql
code/stats.py         # def handle(ctx, params): ...
```
```python
import statistics

def handle(ctx, params):
    r = ctx.sql("select n from measurements")          # فقط SELECT/WITH
    vals = [row[0] for row in r["rows"]]
    ctx.log("تعداد", len(vals))
    return {"columns": ["شاخص", "مقدار"], "rows": [["میانگین", statistics.mean(vals)]]}
```
- فهرست `handlers` مانیفست باید دقیقاً با فایل‌های `code/<نام>.py` یکی باشد؛ کد در بسته‌ی `tier = 1` رد می‌شود.
- `ctx.sql(query, params)` ← `{"columns", "rows"}`؛ حداکثر ۲۰ پرس‌وجو در هر اجرا و ۲۰۰۰ ردیف در هر پرس‌وجو؛ `ctx.log` (`print` هم همین است).
- خروجی: `{"columns": [...], "rows": [[...]]}` (JSON، حداکثر ۱ مگابایت). بلوک جدول ۲۰۰ ردیف اول را نشان می‌دهد.

## چه چیزی مجاز است
- **واردات فقط از فهرست سفید**: math, json, statistics, datetime, itertools, functools, collections, re, decimal, fractions, typing, dataclasses, string, textwrap, heapq, bisect, random, operator, enum, copy, hashlib, base64, unicodedata, zlib, array, numbers, time, calendar, uuid. هر چیز دیگر (os, sys, socket, subprocess, importlib …) رد می‌شود.
- ممنوع: `eval/exec/compile/open/getattr/setattr/globals/__import__` و هر ویژگی یا نام `__dunder__`، `global/nonlocal`، کد ناهم‌گام.
- بررسی ایستای AST هنگام بارگذاری انجام می‌شود و خطا را با شماره‌ی خط می‌گوید (مرحله‌ی «کد سطح ۲» در گزارش بسته).

## مدل امنیتی (صادقانه)
۱. **مرز اصلی کانتینر `plugin-runner`** است: بدون شبکه‌ی بیرون (شبکه‌ی `internal`)، بدون راز و بدون اتصال پایگاه داده‌ی پنل، کاربر غیر root، فایل‌سیستم فقط‌خواندنی، `cap_drop: ALL`، سقف حافظه/CPU/پردازه.
۲. هر اجرا یک زیرپردازه‌ی تازه با `python -I -S` (بدون site-packages)، محیط خالی، `rlimit` (حافظه، CPU، فایل، بدون ساخت پردازه، بدون نوشتن فایل) و مهلت زمانی؛ پایان اجرا = کشتن گروه پردازه.
۳. کد فقط از راه یک پل با `ctx.sql` به داده می‌رسد؛ پل با **توکن کار امضاشده‌ی ۶۰ ثانیه‌ای برای یک پایگاه داده** و **نقش فقط‌خواندنی مشتری** اجرا می‌شود، نه ادمین.
۴. فهرست سفید واردات و بررسی AST **مرز امنیتی نیستند**؛ لایه‌ی اولِ جلوگیری از خطا و کد مشکوک‌اند (جعبه‌ی پایتونی هیچ‌وقت کاملاً نفوذناپذیر نیست).
۵. بسته باید امضای ناشر معتبر داشته باشد و فعال‌سازی اصل دونفره و تأیید تازه دارد (همان `packages.md`).

## استقرار
- `PLUGIN_RUNNER_MODE`: `off` (پیش‌فرض تولید: بلوک‌های handler پیام «فعال نیست» نشان می‌دهند) | `local` (توسعه و آزمون؛ **جداسازی کانتینری ندارد**، در تولید استفاده نشود) | `remote`.
- برای `remote` در web: `PLUGIN_RUNNER_URL=http://plugin-runner:8090`، `PLUGIN_RUNNER_CALLBACK=http://web:8000`، `PLUGIN_RUNNER_TOKEN` (همان `RUNNER_TOKEN` سرویس) و `web` در `DJANGO_ALLOWED_HOSTS`.
- سرویس `plugin-runner` در `docker-compose.yml` است (entrypoint ایمیج عمداً خالی تا pip/migrate اجرا نشود).
- هر اجرا معیار `handler_runs` را می‌شمارد (سقف مجوز: `handler_runs_per_month` را پلاگین می‌تواند بسنجد).

## ورود و خروج داده (docs/adr/0005)
صفحه‌ی کیت می‌تواند فایل بگیرد و جدول بسازد یا خروجی اختصاصی بدهد. **کد فقط تبدیل می‌کند؛ هسته می‌نویسد.**
```toml
need = "editor"                  # ورود = نوشتن
[[imports]]
key = "gps"
title = "ورود فایل دستگاه GPS"
handler = "parse_gps"            # در handlers بسته
extensions = [".trk"]
[[exports]]
key = "rep"
title = "گزارش اختصاصی"
handler = "to_report"
format = "csv"                   # csv | json | txt | geojson
```
```python
def parse_gps(ctx, params):                  # params: {filename, size}
    rows = [...]                             # از ctx.file() (bytes، حداکثر ۳ مگابایت)
    return {"columns": [{"name": "at", "type": "timestamptz"}, {"name": "lat", "type": "double"}, {"name": "lon", "type": "double"}],
            "rows": rows, "geometry": {"lat": "lat", "lon": "lon"}}   # geometry اختیاری: نقطه‌ی WGS84

def to_report(ctx, params):
    r = ctx.sql("select ...")
    return {"filename": "report", "text": "a,b\n1,2\n"}
```
- **ورود:** هسته جدول **تازه** `public.<نام>` می‌سازد (نام را کاربر می‌دهد؛ جدول موجود = خطا؛ بدون append/overwrite). نوع ستون: `text`، `integer`، `bigint`، `double`، `boolean`، `date`، `timestamptz`، `jsonb`. سقف: ۳ مگابایت فایل، ۲۰٬۰۰۰ ردیف، ۵۰ ستون، ۱۰٬۰۰۰ نویسه در هر سلول، نتیجه ۴ مگابایت. نام ستون `geom` رزرو است. مختصات باید در WGS84 باشد.
- **خروجی:** فقط `attachment` با Content-Type قالب (هرگز HTML)، `nosniff`، `no-store`؛ نام فایل پاک‌سازی و پسوند قالب همیشه آخر نام است؛ سقف ۴ مگابایت؛ JSON/GeoJSON باید معتبر باشد.
- هر اجرا: سطح دسترسی صفحه، مجوز پلاگین، CSRF، معیار `io_runs` (سقف `io_runs_per_month`)، ثبت در گزارش فعالیت پایگاه، و قطع‌کن خودکار. گزارش بررسی بسته «جدول تازه (handler)» را در مرحله‌ی «دسترسی نوشتن» نشان می‌دهد.

## قطع‌کن خودکار
اگر کد یک پلاگین بسته پشت‌سرهم خطا بدهد، همان نسخه خودکار کنار گذاشته می‌شود (`kernel.health`):
- هر اجرای handler و هشدار نتیجه‌اش را ثبت می‌کند. **فقط خطای خود کد** (استثنا، مهلت، سقف منابع، خروجی نامعتبر) شمرده می‌شود؛ خاموش بودن یا در دسترس نبودن runner تقصیر پلاگین نیست و شمرده نمی‌شود.
- worker هر دقیقه می‌گذرد: در ۳۰ دقیقه‌ی اخیر اگر دست‌کم ۲۰ اجرا و دست‌کم ۵۰٪ ناموفق باشد، قطع می‌شود.
- اقدام: **بازگشت به آخرین نسخه‌ی تأییدشده‌ی قبلی** که خودش قطع نشده و از نسخه‌ی فعلی پایین‌تر است؛ اگر نبود، پلاگین خاموش می‌شود. نسخه‌ی قطع‌شده دیگر هدف بازگشت نیست و فعال‌سازی دوباره‌اش با مدیر است (اصل دونفره سر جایش).
- ردپا: پنل ← «قطع‌های خودکار پلاگین» (فقط‌خواندنی) و اعلان به مدیران کل. شمارنده‌ی پلاگین پس از قطع صفر می‌شود.
- پوشش: فقط کد سطح ۲. خطای صفحه‌ی اعلانی (SQL) معمولاً مربوط به داده‌ی یک مشتری است و عمداً شمرده نمی‌شود تا مشکل یک پایگاه کل پلاگین را خاموش نکند.

## هنوز نیست
اجرای پس‌زمینه (نوع کار)، آزمون خودکار بسته در runner، ورود/خروج فایل بزرگ‌تر از ۳ مگابایت، append/overwrite، ورود در مودال اصلی، سقف هم‌زمانی هر پلاگین، استودیو برای سطح ۲، و قطع‌کن خودکار.
