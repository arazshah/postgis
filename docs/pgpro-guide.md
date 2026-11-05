# راهنمای pgpro (دستگاه آفلاین روی NanoPi NEO3)

برای توسعه‌دهنده و پشتیبان فنی. طرح و دلیل تصمیم‌ها: `docs/pgpro-plan.md`. این شاخه (`pgpro`) هرگز به `main` ادغام نمی‌شود؛ فقط `main` گاهی در آن ادغام می‌شود.

## وضعیت (فاز ۱)
- کد حالت دستگاه، لایه‌ی سیستم، ساخت ایمیج و آزمون دود **نوشته و در chroot روی x86 (Ubuntu 24.04) آزموده شده‌اند**.
- **روی برد واقعی هنوز آزموده نشده**؛ ایمیج هم هنوز ساخته نشده. فهرست آزمون پایین همین‌ها را روشن می‌کند.
- ایمیج پایه: `PGPRO_BASE_IMAGE` (پیش‌فرض `https://dl.armbian.com/nanopineo3/Trixie_current_minimal`). **بررسی شد:** این آدرس به ساخت
  «community» Armbian (`26.11.0-trunk.120`، Debian 13 Trixie، هسته‌ی 6.18.60، minimal) می‌رود. یعنی برای NEO3 پشتیبانی **community** است، نه رسمی/پایدار؛
  نسخه‌های trunk ممکن است از ساختی به ساخت دیگر عوض شوند. برای ثابت ماندن، آدرس مستقیم یک نسخه‌ی مشخص را در ورودی `base_image` بدهید.
- ساخت با هش `.sha` کنار ایمیج تطبیق داده می‌شود و اگر نخواند متوقف می‌شود.
- ساختار ایمیج بررسی شد: جدول msdos، یک پارتیشن ext4 (از سکتور ۳۲۷۶۸)، شبکه با netplan + systemd-networkd (نه NetworkManager)، `systemd-resolved` و
  `openssh-server` از پیش نصب‌اند. تنظیم شبکه‌ی pgpro (`05-pgpro-eth.network`، DHCP + link-local) و LLMNR روی همین پایه نوشته شد.

## ساخت ایمیج
1. کلید عمومی SSH خودتان را در `image/support_keys.pub` بگذارید (یک خط؛ فقط کلید عمومی).
2. GitHub ← Actions ← «pgpro image» ← Run workflow (نسخه‌ی `0.1.0`). حدود ۲۰ تا ۴۰ دقیقه؛ آزمون دود داخل ساخت است و اگر بخورد ایمیج تولید نمی‌شود.
3. خروجی `pgpro-0.1.0-nanopineo3.img.xz` و `.sha256` در Artifacts (یا Release پیش‌نویس).
4. محلی (روی هاست arm64 با root): `sudo PGPRO_VERSION=0.1.0 bash image/build/remaster.sh ./out`.

## نوشتن کارت و اولین بوت
- با balenaEtcher روی microSD (≥ ۳۲ گیگ، A1/A2) بنویسید؛ کابل شبکه و برق ۵V/۲A؛ ۳ تا ۵ دقیقه صبر.
- در این مدت `http://pgpro.local` صفحه‌ی «در حال آماده‌سازی» را نشان می‌دهد؛ سپس صفحه‌ی ورود.
- ورود `admin` / `pgpro` ← رمز تازه اجباری ← داشبورد. کاربران از منوی حساب ← «کاربران».

## به‌روزرسانی بدون نوشتن دوباره‌ی کارت
هر ساخت روی شاخه‌ی `pgpro` علاوه بر ایمیج کامل، یک **بسته‌ی به‌روزرسانی** (کد + فایل‌های استاتیک + تنظیم سیستم، حدود ۹۰ مگابایت) می‌سازد و در Release با برچسب
[`pgpro-latest`](https://github.com/arazshah/postgis/releases/tag/pgpro-latest) می‌گذارد. دستگاه با `pgpro-update` آن را می‌گیرد و اعمال می‌کند:
بکاپ دیتابیس پنل ← نصب کنار نسخه‌ی قبلی ← مایگریشن ← راه‌اندازی دوباره ← بررسی سلامت؛ اگر سالم بالا نیامد، کد خودکار برمی‌گردد. داده‌ها و کاربران دست نمی‌خورند.

- **از پنل (دستگاه به اینترنت وصل است):** منوی حساب ← «دستگاه» ← «بررسی و به‌روزرسانی».
- **با SSH:** `sudo pgpro-update --latest` (فقط بررسی: `--check`، برگشت: `--rollback`).
- **دستگاه بدون اینترنت:** بسته را از Release (یا Artifacts) بردارید و `scp -i ~/.ssh/pgpro_support pgpro-update-latest.tar.xz support@pgpro.local:/tmp/` بزنید، سپس `sudo pgpro-update /tmp/pgpro-update-latest.tar.xz`.
- **یک‌بار نصب ابزار روی دستگاهی که ایمیج قدیمی دارد** (ایمیج‌های `dev4` و قدیمی‌تر ابزار را ندارند؛ فقط همین یک بار):
  ```bash
  ssh -i ~/.ssh/pgpro_support support@pgpro.local
  curl -fL -o /tmp/u.tar.xz https://github.com/arazshah/postgis/releases/download/pgpro-latest/pgpro-update-latest.tar.xz
  curl -fL -o /tmp/u.tar.xz.sha256 https://github.com/arazshah/postgis/releases/download/pgpro-latest/pgpro-update-latest.tar.xz.sha256
  sudo tar -xJf /tmp/u.tar.xz -C / --strip-components=1 rootfs/usr/local/sbin/pgpro-update
  sudo pgpro-update /tmp/u.tar.xz
  ```
- **محدودیت‌ها:** اگر `requirements.txt` عوض شود، دستگاه باید بسته‌های پایتون را از اینترنت بگیرد (وگرنه خطای روشن می‌دهد و ایمیج کامل لازم است). ویدیوهای راهنما و نقشه‌ی پایه در بسته نیستند و با ایمیج کامل عوض می‌شوند. مایگریشن‌های دیتابیس برگشت‌پذیر نیستند؛ بکاپ پنل در `/var/lib/pgpro/backups/panel` می‌ماند.
- **امضا (اختیاری، پیشنهادی قبل از فروش):** یک جفت کلید ed25519 بسازید (`openssl genpkey -algorithm ed25519 -out sign.pem`؛ کلید عمومی با `openssl pkey -in sign.pem -pubout`)، کلید عمومی را در `image/update.pub` بگذارید و کلید خصوصی را به‌عنوان secret با نام `PGPRO_UPDATE_SIGN_KEY` در GitHub ثبت کنید. بعد از آن، دستگاه فقط بسته‌ی امضاشده می‌پذیرد.

## نقشه‌ی پایه‌ی ایران (آفلاین)
- در ساخت ایمیج، محدوده‌ی ایران از ساخت روزانه‌ی Protomaps (داده‌ی OpenStreetMap) تا **بزرگنمایی ۱۴** بریده و در `/opt/pgpro/basemap/iran.pmtiles` گذاشته می‌شود
  (کش ماهانه در Actions؛ اندازه‌ی واقعی در لاگ ساخت چاپ می‌شود). در اولین بوت یک symlink آن را به `OSM_ROOT/basemap` می‌برد تا «بازنشانی کارخانه» پاکش نکند.
- نقشه‌های چندلایه، انتشار و نقشه‌ی عمومی (MapLibre) و پیش‌نمایش جدول، کنسول SQL و یافتن عارضه (Leaflet + افزونه‌ی محلی `maplibre-gl-leaflet`) از همین فایل استفاده می‌کنند؛ هیچ درخواستی به اینترنت نمی‌رود.
- بعد از بزرگنمایی ۱۴ نقشه بزرگ‌تر نشان داده می‌شود ولی جزئیات تازه‌ای نمی‌آید. برای تغییر: `--maxzoom` در `.github/workflows/pgpro-image.yml` (و کلید کش).

## تنظیمات پیشرفته (Django admin)
`/manage/` در دستگاه **بسته است** (۴۰۴). نام سایت، پلن و بقیه را `device_init` می‌گذارد؛ تغییر دستی فقط با SSH: `sudo pgpro-manage shell`.

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
6. درون‌ریزی یک Shapefile/GeoPackage ۱۰ تا ۵۰ مگابایتی؛ نمایش روی نقشه (زیر لایه‌ها نقشه‌ی پایه‌ی ایران دیده شود، حتی با کابل اینترنت جدا؛ برچسب‌ها فارسی).
7. اتصال QGIS از رایانه‌ی دیگر با رشته‌ی اتصال پایگاه.
8. بکاپ دستی و بازگردانی از «بکاپ‌ها».
9. صفحه‌ی «دستگاه»: IP، حافظه، فضا؛ دکمه‌ی همگام‌سازی ساعت (تاریخ بعد از آن درست شد؟).
10. قطع ناگهانی برق در حال کار، روشن‌کردن دوباره: همه‌چیز بالا می‌آید؟
11. SSH با کلید؛ ورود با رمز باید رد شود.
12. هنگام کار با ۲ کاربر هم‌زمان: خروجی `free -m` و `uptime` (مصرف حافظه و بار).
13. `ssh` + `sudo pgpro-manage device_reset_password admin` کار می‌کند؟

## محدودیت‌های فاز ۱ (عمداً)
HTTP ساده (برداشت میدانی/GNSS و موقعیت مرورگر کار نمی‌کند و در دستگاه خاموش است)، بدون QGIS Server/WMS/WFS و داده‌ی آماده‌ی ایران،
بدون به‌روزرسانی آفلاین، بدون SSD، بدون LLMNR/NetBIOS برای `http://pgpro/`.
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
