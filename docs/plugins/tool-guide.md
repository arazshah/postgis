# راهنمای نوشتن ابزار تحلیل (پلاگین ابزار)

مرجع معماری: `docs/adr/0001-tool-plugins.md` و `docs/adr/0004-kernel-and-plugins.md`.

## ابزار تازه = یک ماژول
یک فایل در `tools/plugins/<کلید>.py` بسازید (یا در اپ دیگر: `<app>/geotools.py`). فایل خودکار بار می‌شود؛ **هیچ فایل دیگری را تغییر ندهید**.

```python
from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Centroid(ToolPlugin):
    key, order, category, icon = "centroid", 170, "proximity", "t-buffer"
    title = "مرکز عارضه"
    description = "مرکز هر عارضه را به‌صورت نقطه می‌دهد."
    inputs, output = ("هر لایه",), "نقطه"
    example = "مرکز هر محله برای برچسب‌گذاری."
    columns = ("ستون‌های لایه ورودی", "geom")
    params = (Param("layer", "layer", "لایه ورودی"),)

    def build(self, ctx):
        t = ctx.table("layer")                      # لایه‌ی انتخاب‌شده (نبودنش = خطای فارسی)
        col, srid, _ = sdk.geom_of(t)               # نام ستون مکانی و SRID
        return sql.SQL("SELECT {attrs}ST_Centroid({g}) AS geom FROM {src} s WHERE s.{c} IS NOT NULL").format(
            attrs=sdk.attr_sql(ctx.ex, t, "s"), g=sdk.geom4326("s", col, srid), src=sdk.ident(t), c=sql.Identifier(col))
```

## قرارداد
| جزء | توضیح |
|---|---|
| `key` | یکتا، حروف کوچک لاتین، حداکثر ۲۰ نویسه |
| `category` | یکی از دسته‌های ثبت‌شده (`sdk.category(...)`)؛ دسته‌ی تازه را در `plugin.py` اپ خود ثبت کنید |
| `icon` | نام آیکون در `core/icons.py` (و `static/js/studio-ui.js`)؛ ایموجی ممنوع |
| `params` | فیلدهای فرم: `layer` (با `geom="point|line|polygon"`)، `number`، `text`، `choice` (چیپ)، `bool` |
| `build(ctx)` | فقط **SELECT نتیجه** با ستون `geom`؛ باید `psycopg.sql.Composable` باشد (رشته‌ی خام رد می‌شود) |
| `summary_extra(params)` | اختیاری: تکه‌های ویژه‌ی خلاصه‌ی تاریخچه |
| `after_create(conn, target)` | اختیاری: بررسی پس از ساخت جدول در همان تراکنش |
| `chart_hint` | اختیاری: پیشنهاد نمودار برای نتیجه |
| `needs_routing` | ابزار شبکه‌ی معابر (`routing.ways`) می‌خواهد؛ در `build` هم `ctx.need_routing()` را صدا بزنید |

موتور (`tools/engine.py`) بقیه را یکسان انجام می‌دهد: اجرای SELECT با **نقش خود مشتری** و مهلت ۳ دقیقه، تنظیم نوع هندسه و SRID 4326، کلید `gid`، نمایه‌ی GiST، `ANALYZE` و واگذاری مالکیت.

## قواعد امنیتی (الزامی)
- نام جدول و ستون فقط با `sql.Identifier`؛ مقدار فقط با `sql.Literal`. هرگز f-string یا الحاق رشته با ورودی کاربر.
- ورودی را با `ctx.number(name, lo, hi)`، `ctx.table(name)`، `ctx.cols(t)` / `ctx.attr_cols(t)` اعتبارسنجی کنید؛ خطا = `ToolError` با پیام کوتاه فارسی.
- برای ابزار سنگین سقف بگذارید: `ctx.guard(t, col, cap, "پیام")`.
- ماژول ابزار فقط `tools.sdk` و `psycopg.sql` را import می‌کند (`lint-imports` این را اجبار می‌کند).

## آزمون (الزامی)
1. موردهای ابزار را به `CASES` در `tools/tests/golden.py` اضافه کنید: دست‌کم یک ورودی درست و یک ورودی نادرست.
2. `python -m tools.tests.golden` فایل طلایی را بازتولید می‌کند؛ diff آن را بازبینی کنید (فقط ابزار شما باید تغییر کرده باشد).
3. آزمون اجرای واقعی روی PostGIS (با `TEST_PG_HOST`) مثل `analysis/tests/test_new_tools.py`.
4. `DJANGO_TESTING=1 python manage.py test tools analysis`؛ `python manage.py check`؛ `ruff check .`؛ `lint-imports`.

## راهنما
مقاله یا بخش ابزار را در `kb/content/analysis/` اضافه کنید و `python manage.py kb_check` را اجرا کنید.
