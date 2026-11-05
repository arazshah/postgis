# راهنمای pgpro (دستگاه آفلاین روی NanoPi NEO3)

برای توسعه‌دهنده و پشتیبان فنی. طرح و دلیل تصمیم‌ها: `docs/pgpro-plan.md`. این شاخه (`pgpro`) هرگز به `main` ادغام نمی‌شود؛ فقط `main` گاهی در آن ادغام می‌شود.

## وضعیت (فاز ۱)
- کد حالت دستگاه، لایه‌ی سیستم، ساخت ایمیج و آزمون دود **نوشته و در chroot روی x86 (Ubuntu 24.04) آزموده شده‌اند**.
- **روی برد واقعی هنوز آزموده نشده**؛ ایمیج هم هنوز ساخته نشده. فهرست آزمون پایین همین‌ها را روشن می‌کند.
- ایمیج پایه: `PGPRO_BASE_IMAGE` (پیش‌فرض `https://dl.armbian.com/nanopineo3/Trixie_current_minimal`). **وجود این ایمیج برای NEO3 تأیید نشده است**؛
  اگر نبود، یکی از ایمیج‌های رسمی NEO3 را از سایت Armbian بردارید و آدرسش را در ورودی `base_image` گردش‌کار بدهید
  (Debian Trixie یا Bookworm، نسخه‌ی minimal/CLI).

## ساخت ایمیج
1. کلید عمومی SSH خودتان را در `image/support_keys.pub` بگذارید (یک خط؛ فقط کلید عمومی).
2. GitHub ← Actions ← «pgpro image» ← Run workflow (نسخه‌ی `0.1.0`). حدود ۲۰ تا ۴۰ دقیقه؛ آزمون دود داخل ساخت است و اگر بخورد ایمیج تولید نمی‌شود.
3. خروجی `pgpro-0.1.0-nanopineo3.img.xz` و `.sha256` در Artifacts (یا Release پیش‌نویس).
4. محلی (روی هاست arm64 با root): `sudo PGPRO_VERSION=0.1.0 bash image/build/remaster.sh ./out`.

## نوشتن کارت و اولین بوت
- با balenaEtcher روی microSD (≥ ۳۲ گیگ، A1/A2) بنویسید؛ کابل شبکه و برق ۵V/۲A؛ ۳ تا ۵ دقیقه صبر.
- در این مدت `http://pgpro.local` صفحه‌ی «در حال آماده‌سازی» را نشان می‌دهد؛ سپس صفحه‌ی ورود.
- ورود `admin` / `pgpro` ← رمز تازه اجباری ← داشبورد. کاربران از منوی حساب ← «کاربران».

## ابزارهای پشتیبان (با SSH کاربر `support`، فقط کلید)
```bash
ssh support@pgpro.local
sudo pgpro-manage device_reset_password admin      # رمز مدیر ← pgpro
sudo pgpro-manage shell                            # پوسته‌ی جنگو با تنظیمات دستگاه
sudo journalctl -u pgpro-firstboot -u pgpro-web -u pgpro-worker -e
cat /var/lib/pgpro/firstboot.log                   # گزارش اولین بوت (روی کارت می‌ماند)
sudo pgpro-factory-reset --yes                     # پاک‌کردن همه‌چیز و تکرار اولین بوت (برگشت‌ناپذیر)
```

## چیدمان دستگاه
| مسیر | محتوا |
|---|---|
| `/opt/pgpro/releases/<نسخه>`، `/opt/pgpro/current`، `/opt/pgpro/venv` | کد، لینک نسخه‌ی فعال، محیط پایتون (فقط‌خواندنی) |
| `/etc/pgpro/pgpro.env` | رمزها و کلید رمزنگاری یکتای دستگاه (۰۶۴۰). **پاک‌شدنش یعنی رمزهای ذخیره‌شده دیگر خوانده نمی‌شوند.** |
| `/var/lib/pgpro/{media,backups,ows,osm,rasters,imports}` | داده‌ی برنامه و بکاپ‌ها |
| `/var/lib/postgresql/<نسخه>/main` | خوشه‌ی PostgreSQL (دیتابیس `panel` + پایگاه‌های کاربران `gp_*`) |
| سرویس‌ها | `pgpro-sshkeys`، `pgpro-firstboot` (یک‌بار)، `pgpro-web` (gunicorn)، `pgpro-worker`، `nginx`، `avahi-daemon`، `postgresql` |

PostgreSQL روی شبکه‌ی محلی باز است (`pg_hba`: فقط 10/8، 172.16/12، 192.168/16، link-local) برای QGIS؛ نقش‌های داخلی `pgpro_admin` و `pgpro_panel` فقط از خود دستگاه.
آدرس اتصال هر پایگاه در صفحه‌ی خودش: `pgpro.local:5432`.

## فهرست آزمون روی برد (نتیجه‌ی هر بند را برای من بفرستید)
1. بوت: کارت نوشته شد، LED/شبکه بالا آمد؟ چند دقیقه تا دیده شدن در شبکه؟ (IP را از روتر هم بخوانید.)
2. `http://pgpro.local` از ویندوز، مک/لینوکس و گوشی باز می‌شود؟ (اگر نه: با IP امتحان کنید.)
3. صفحه‌ی «در حال آماده‌سازی» دیده شد و بعد صفحه‌ی ورود آمد؟ زمان کل اولین بوت؟
4. ورود `admin/pgpro`، تغییر رمز اجباری، خروج و ورود با رمز تازه.
5. ساخت کاربر دوم، ورود با او، ساخت پایگاه با PostGIS و pgRouting.
6. درون‌ریزی یک Shapefile/GeoPackage ۱۰ تا ۵۰ مگابایتی؛ نمایش روی نقشه (بدون نقشه‌ی پایه، پس‌زمینه ساده است).
7. اتصال QGIS از رایانه‌ی دیگر با رشته‌ی اتصال پایگاه.
8. بکاپ دستی و بازگردانی از «بکاپ‌ها».
9. صفحه‌ی «دستگاه»: IP، حافظه، فضا؛ دکمه‌ی همگام‌سازی ساعت (تاریخ بعد از آن درست شد؟).
10. قطع ناگهانی برق در حال کار، روشن‌کردن دوباره: همه‌چیز بالا می‌آید؟
11. SSH با کلید؛ ورود با رمز باید رد شود.
12. هنگام کار با ۲ کاربر هم‌زمان: خروجی `free -m` و `uptime` (مصرف حافظه و بار).
13. `ssh` + `sudo pgpro-manage device_reset_password admin` کار می‌کند؟

## محدودیت‌های فاز ۱ (عمداً)
HTTP ساده (برداشت میدانی/GNSS و موقعیت مرورگر کار نمی‌کند و در دستگاه خاموش است)، بدون QGIS Server/WMS/WFS و داده‌ی آماده‌ی ایران،
بدون نقشه‌ی پایه (بعداً بارگذاری)، بدون به‌روزرسانی آفلاین، بدون SSD، بدون LLMNR/NetBIOS برای `http://pgpro/`.
مقاله‌های پایگاه دانش مربوط به پرداخت/پیامک هنوز در دستگاه دیده می‌شوند (فقط متن).

## توسعه
```bash
DJANGO_SETTINGS_MODULE=config.settings_device DJANGO_TESTING=1 python manage.py test device   # آزمون‌های دستگاه
DJANGO_TESTING=1 python manage.py test                                                         # آزمون‌های ابری (نباید خراب شود)
shellcheck image/build/*.sh image/overlay/*.sh image/overlay/rootfs/usr/local/sbin/*
git merge origin/main   # گاهی؛ هرگز برعکس
```
نقطه‌های اتصال در فایل‌های مشترک (برای حل تعارض ادغام): `accounts/views.py` (۳ شرط `DEVICE_MODE`)، `core/templatetags/ws.py` (`DEVICE_HIDDEN_VIEWS`)،
`templates/base.html`، `templates/accounts/profile.html`، `templates/databases/dashboard.html`، چند قالب راهنما/پایگاه دانش (`{% if not DEVICE_MODE %}`).
