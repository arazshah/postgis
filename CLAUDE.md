# راهنمای کار روی ژئوپایگاه

ژئوپایگاه سرویس PostGIS آماده است: Django (پنل، فارسی، راست‌به‌چپ) + PostgreSQL/PostGIS برای دیتابیس مشتریان.
زبان رابط و متن‌ها **فارسی** است؛ پیام commit و توضیح کد هم فارسی.

## معماری: هسته + پلاگین (الزامی)
مرجع: `docs/adr/0004-kernel-and-plugins.md` (و ۰۰۰۱ تا ۰۰۰۳). در حال مهاجرت تدریجی هستیم:
- `kernel/` هسته است و **هیچ اپی را import نمی‌کند**. هر اپ یک پلاگین است و در `<app>/plugin.py` خودش را معرفی و سهم‌هایش را ثبت می‌کند.
- چیز تازه را با ثبت در نقطه‌ی توسعه اضافه کنید، نه با افزودن به فهرست ثابت: نوع کار پس‌زمینه و کار دوره‌ای (`kernel.jobs`)، بخش ریل، کار سریع خانه و ناوبری ادمین (`kernel.nav`)، زبانه و بخش صفحه‌ی تنظیمات و ابزار آزمایش آن (`kernel.settings`)، ردیف‌های داشبورد و جست‌وجوی پنل مدیریت (`kernel.dash`).
- `core` (سایت و قاب پنل) فقط `accounts`، `databases` و `kb` را می‌شناسد؛ رمزنگاری مقدارهای حساس در `kernel.crypto` است.
- اتصال به پایگاه داده‌ی مشتری فقط از `kernel.tenantdb` (`tenantdb.catalog(db)` یا `tenantdb.connect(db, write=..., as_owner=...)`)؛ نوشتن با `as_owner=True`، بدون `SET ROLE` دستی. `databases.explorer` فقط برای خود بخش داده است.
- دسترسی به فضای کار (سطح کاربر، میزبان PostGIS، ساخت پایگاه، اعلان)، ورود/خروج GDAL و رمزنگاری از قراردادهای هسته می‌آید: `kernel.workspace`، `kernel.dataio`، `kernel.crypto`. از `databases` فقط `databases.models` (هدف کلید خارجی) برای بخش‌های دیگر مجاز است (`databases.nl2sql` فقط برای تحلیل)؛ `lint-imports` بقیه را رد می‌کند.
- زبانه‌ی تازه‌ی پروفایل کاربر با `kernel.profile` ثبت می‌شود (نمونه: `analysis/profile.py`). قابلیت‌ها به خانه، مصرف، پنل مدیریت، رویدادهای فضای کار و جدول با `kernel.home`، `kernel.events` و `kernel.dash` سهم می‌دهند؛ پلاگین سیستمی (حساب، پایگاه داده، کارها، صورتحساب، پشتیبانی، اعلان، راهنما، آمار) هرگز پلاگین قابلیت را import نمی‌کند (قرارداد سخت در `lint-imports`).
- ابزار تحلیل تازه = یک ماژول در `tools/plugins/` طبق `docs/plugins/tool-guide.md` (موتور: `tools/engine.py`، قرارداد: `tools/sdk.py`)؛ SQL هر ابزار با آزمون طلایی (`tools/tests/golden.py`) قفل است.
- پلاگین غیرسیستمی را مدیر از «پلاگین‌ها و مجوزها» در پنل روشن/خاموش یا به دارندگان مجوز (همه، پلن، سازمان، کاربر، فضای کار) محدود می‌کند (`kernel.entitlements`، دروازه‌ی آدرس `kernel.gate`). منو و آدرس پلاگین خاموش یا بدون مجوز ناپدید است (۴۰۴)؛ نمای عمومی یک پلاگین محدود (مثلاً دریافت داده‌ی دستگاه) را عمداً با `@gate.public` علامت بزنید و احراز هویتش را خودتان انجام دهید. در آزمون، بعد از ساخت `PluginState` حتماً `addCleanup(entitlements.invalidate)`.
- `lint-imports` قاعده‌های وابستگی را اجبار می‌کند؛ قرارداد تازه اضافه کنید، قرارداد موجود را شل نکنید.
- پلاگین معیوب نباید سایت را بخواباند: خطای بارگذاری در `manage.py check` (شناسه‌های `kernel.E*`) دیده می‌شود.

## رابط کاربری (الزامی)
هر چیز تازه در رابط باید از **سیستم طراحی** پیروی کند: `docs/design-system.md`. خلاصه:
- فضای کار تمام‌عرض، یک منوی اصلی (نوار بالا + ریل کناری پایگاه)، بدون «حالت گسترده».
- کار چندمرحله‌ای در مودال؛ عملیات هر ردیف/کارت در منوی ⋯؛ انتخاب از گزینه‌های کم با چیپ/کاشی، نه select با متن طولانی.
- آیکون فقط از `core/icons.py` (`{% icon %}`) یا `StudioUI.icon`؛ ایموجی و نماد متنی ممنوع.
- رنگ و اندازه فقط با توکن CSS (`ds.css` و `app.css`)؛ صفحه‌های یک پایگاه از `databases/_ws.html` ارث می‌برند.
- هر صفحه در ۴۰۰ پیکسل سالم باشد؛ حالت خالی و خطا طراحی شود.
- نمونه‌ی مرجع: استودیوی نقشه (`templates/maps/composer.html`) و قاب برنامه (`templates/base.html`).

## آزمون و کیفیت
- `DJANGO_TESTING=1 python manage.py test` (آزمون‌های PostGIS بدون `TEST_PG_HOST` skip می‌شوند)؛ `ruff check .`؛ `lint-imports`
- تغییر رابط را با Playwright روی دسکتاپ و ۴۰۰ پیکسل ببینید (Chromium نصب است).
- راهنما و پایگاه دانش (`kb/content`) را با رابط هماهنگ نگه دارید؛ `python manage.py kb_check`.
- بدون درخواست صریح، PR نسازید؛ روی شاخه‌ی تعیین‌شده کار و push کنید.

- بسته‌ی سطح ۲ برای هر handler فایل `tests/<handler>.toml` (آزمون اعلانی، kernel.pkgtest) می‌خواهد؛ اجرایش فقط در runner.
- ورود/خروج داده با handler: کد فقط تبدیل می‌کند و `kernel.pluginio` می‌نویسد (جدول تازه، INSERT پارامتری)؛ خروجی فقط attachment با نوع فهرست سفید.
- قطع‌کن خودکار (`kernel.health`): نتیجه‌ی اجرای کد سطح ۲ را فقط با خطای خود کد (`HandlerFailed`) بشمارید، نه خرابی زیرساخت.
- کد سطح ۲ فقط در بسته‌ی tier = 2 و فقط اجرا در plugin-runner؛ docs/plugins/tier2.md. حالت local فقط توسعه/آزمون است.
- استودیوی پلاگین (`kernel.studio`) فقط پیش‌نویس و خروجی بدون امضا می‌سازد؛ امضا همیشه بیرون از سرور است. اجرای آزمایشی handler فقط از `client.run_files` (مدل‌آگاه) و فقط پس از بررسی ایستا و تأیید تازه.
- نوشتن از صفحه‌ی کیت فقط با `[[forms]]` (INSERT)، `[[ingest]]`، `[[sources]]` و `[[records]]` (UPDATE/DELETE فقط روی `id` و ستون‌های اعلام‌شده، فقط جدول `[[tables]]` همان صفحه، docs/plugins/geometry.md) — همه ساخته‌ی هسته؛ SQL نوشتنی از پلاگین پذیرفته نمی‌شود. فیلد `geometry` را `kernel.geomval` + `ST_IsValid` می‌سنجد.
- فروش پلاگین: افزونه‌ی billing.PluginAddon و فاکتور نوع addon؛ مجوز فقط با `kernel.entitlements.grant` ساخته می‌شود.
- مصرف پلاگین را با `kernel.metering.record` بشمارید و سقف مجوز را با `metering.check` بسنجید.
- تنظیم هر پلاگین با `kernel.conf` (اعلام گزینه در `plugin.py`، خواندن با `conf.get`؛ نه در جدول تنظیمات سایت).
- ورود دومرحله‌ای پنل مدیریت (TOTP) در `accounts/admin_2fa.py`؛ کار حساس تازه در پنل را با `kernel.stepup.ok(request)` / `stepup.url(request)` محافظت کنید (تأیید تازه). در آزمون `override_settings(ADMIN_2FA_REQUIRED=True)`؛ بازنشانی: `manage.py admin_2fa_reset`.

- بخش‌های داده‌ی یک پایگاه پلاگین جدا هستند (`dbtables`، `dbsql`، `dbfind`، `dbimport`، `dbhealth`، `dbbackup`، `dbusage`، `dbteam`؛ docs/adr/0006). مسیرشان را با `kernel.routes.add("databases", …)` در فضای‌نام `databases` ثبت کنید، نه با افزودن به `databases/urls.py`؛ بخش‌ها دیگری را import نمی‌کنند (قرارداد `independence`) و `databases.views` را هم نه.

- پلاگین سطح ۳ (کد درون‌پردازه، فقط تیم خودمان) در `ext/<id>/` طبق `docs/plugins/tier3.md` و `docs/adr/0007`: با `manage.py ext_new` بسازید، `ext_check` و آزمون خودش را بگذرانید؛ فقط SDK هسته، برچسب اپ `x_<id>`، مسیر فقط در گروه‌های `ext`/`ws_ext`، مهاجرت فقط افزایشی. از پنل بارگذاری نمی‌شود؛ پیش‌فرض «محدود و بدون مجوز» است و مدیر از پنل فعال می‌کند. `PLUGINS_SAFE_MODE=1` راه نجات است.

- ساخت و انتشار پلاگین از پنل (docs/adr/0008): «پلاگین‌ها» (`kernel.hub`، `/manage/plugins/`) همه‌ی کارهای پلاگین را در چهار زبانه جمع می‌کند و ویزارد (`kernel.wizard`، `wizard_code`، `wizard_admin`) از معرفی تا انتشار می‌رود. SQL و TOML را هسته از مشخصات ساخت‌یافته می‌سازد (نام جدول/ستون فقط از فهرست اعلام‌شده)؛ جدول پلاگین با `[[tables]]` (`kernel.tables`، فقط افزایشی) در پایگاه مشتری ساخته می‌شود. انتشار مستقیم با مهر «panel» (`kernel.pkg.seal`، `kernel.publish`)؛ دسترسی و قیمت با `kernel.market` ← `billing.market`؛ بازار مشتری `/billing/market/` و کار دوره‌ای انقضا (`billing.market_jobs`). کد سطح ۲ می‌تواند `import geo` (docs/plugins/geo.md) داشته باشد. هر قابلیت تازه‌ی ویزارد آزمون پذیرش «مانیتورینگ آنلاین» (`kernel/tests/test_acceptance_monitoring.py`) را نشکند.

- توانمندسازهای مشترک (docs/adr/0009): هشدار چندکاناله با `kernel.notify` (`notify.deliver`؛ بله/تلگرام با رله، پشتیبان پیامک/ایمیل؛ تنظیم کانال در پنل). ورود دوره‌ای از API بیرونی با `[[sources]]` (`kernel.sources`، docs/plugins/sources.md): هسته واکشی می‌کند، فقط میزبان تأییدشده‌ی مدیر و سوئیچ «منابع بیرونی» در پنل؛ هر تنظیم تازه‌ی سکو باید در پنل مدیریت باشد، نه Coolify/متغیر محیطی.
- گزارش PDF صفحه با `[[reports]]` (`kernel/reports.py`، docs/plugins/reports.md): قالب را هسته می‌سازد، WeasyPrint با **url_fetcher بسته** (فقط فونت داخلی)؛ هیچ منبع بیرونی/فایل محلی واکشی نشود و خروجی HTML همیشه escape شود. چیدمان قابل‌ویرایش گزارش (`kernel/reportlayout.py`): JSON اعتبارسنجی‌شده با فهرست سفید؛ HTML/CSS آزاد از کاربر هرگز پذیرفته نشود و هر مقدار کاربر که داخل CSS می‌رود با `_css_str` پاک شود.
- ژئوکدر فارسی (`kernel/persian.py`، `kernel/geocode.py`، docs/plugins/geocoder.md): تطبیق روی `osm_*` همان پایگاه در شعاع یک شهر؛ دقت «معبر/مکان» است نه پلاک. آزمایشگاه پنل (`geocode_admin`) فقط مدیر ارشد با `stepup`؛ هر خروجی CSV ورودی کاربر را با `_safe` در برابر تزریق فرمول خنثی کند.

- استودیوی دیداری پلاگین (docs/adr/0010): ساخت از `…/plugindraft/<pk>/designer/`؛ هر تغییر یک «عملیات» در `kernel/blueprint.py` است (مرورگر هرگز TOML/SQL نمی‌فرستد؛ API: `kernel/studio_api.py`، تاریخچه: `PluginDraftRevision`، پیش‌نمایش نمونه: `kernel/sampledata.py`). قابلیت تازه‌ی کیت صفحه را اول به عملیات و نمای استودیو اضافه کنید، نه فقط به TOML.
- قابلیت‌های مشترک ADR-0009 پلاگین مستقل‌اند (`kernel/caps.py`، شناسه‌های `cap_notify`، `cap_sources`، `cap_draw`، `cap_reports`، `cap_geocoder`؛ بدون ردیف وضعیت باز): هر نقطه‌ی ورود تازه‌ی یک قابلیت باید با `caps.allowed(cap, user=..., ws=...)` سنجیده شود و خاموش‌بودن به ۴۰۴ یا بازگشت به رفتار قبلی (مثلاً پیامک/ایمیل) برسد، نه خطا.
- پلاگین قبلی (پیش‌نویس TOML یا نسخه‌ی نصب‌شده) با `kernel/importer.py` به نقشه می‌آید و با `pagekit.Page` راستی‌آزمایی می‌شود؛ آنچه نمی‌گنجد بلوک `raw` است که فقط درون‌ریز می‌سازد (عملیات مرورگر آن را رد می‌کند). قابلیت تازه‌ی کیت صفحه را در درون‌ریز هم جا بدهید تا بلوک خام نشود.
