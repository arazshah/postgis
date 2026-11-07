# سایت pgpro.ir (پایگاه داده مکانی پرو)

سایت استاتیک و فارسی برای معرفی و پیش‌فروش دستگاه آفلاین pgpro. بدون ابزار ساخت و بدون CDN بیرونی:
HTML و CSS خالص، فونت‌ها و آیکون‌ها روی خود سایت، یک فایل جاوااسکریپت کوچک برای منو و فرم.
ظاهر هم‌خانواده‌ی postgis.ir (برگه‌ی نقشه، فیروزه‌ای و اُخرایی، Vazirmatn و Kufi).

## ساختار
| مسیر | محتوا |
|---|---|
| `public/` | خروجی سایت (چیزی که nginx سرو می‌کند) |
| `public/assets/` | CSS، JS، فونت، آیکون‌ها (`icons.svg`)، لوگو، عکس و ویدیوی دستگاه |
| `tools/build_pages.py` | ساخت صفحه‌های HTML از قالب مشترک (`layout.py`، `pages_home.py`، `pages_other.py`) |
| `tools/check_site.py` | بررسی لینک‌ها، لنگرها، sitemap و نبودن style/script درون‌خطی |
| `nginx.conf.template` | تنظیم nginx: نشانی‌های تمیز، هدرهای امنیتی و CSP، کانال `/update/` |
| `Dockerfile`، `docker-compose.yml` | استقرار در Coolify |

## ویرایش
متن هر صفحه در `tools/pages_*.py` است؛ بعد از ویرایش:
```bash
python3 pgpro-site/tools/build_pages.py   # بازسازی public/*.html
python3 pgpro-site/tools/check_site.py    # بررسی
```
خروجی HTML هم در مخزن می‌ماند (CI می‌سنجد که با قالب هماهنگ باشد). رنگ و اندازه فقط با توکن‌های `:root` در `site.css`.
جاوااسکریپت و style درون‌خطی ممنوع است (CSP).

## استقرار در Coolify
1. منبع: مخزن `arazshah/postgis`، شاخه‌ی **`pgpro-web`**.
2. نوع: **Docker Compose**. در شاخه‌ی `pgpro-web` فایل `docker-compose.yml` ریشه همین سایت است: Base Directory برابر `/` و Docker Compose Location برابر `/docker-compose.yml`. (در شاخه‌های دیگر: Base Directory برابر `/pgpro-site`.)
3. دامنه‌ها را در سرویس `web` بگذارید: `https://pgpro.ir` و `https://www.pgpro.ir` (پورت داخلی ۸۰). گواهی TLS را پراکسی Coolify می‌گیرد.
4. رکوردهای DNS (A) برای `pgpro.ir` و `www` را به سرور Coolify بدهید.
5. Deploy. بعد از هر push به `pgpro-web` با Webhook خودکار دوباره ساخته می‌شود (در Coolify «Automatic Deployment» را روشن کنید).
6. سلامت: `https://pgpro.ir/healthz` باید `ok` بدهد.

متغیر اختیاری: `PGPRO_RELEASE_BASE` (مقصد هدایت `/update/*`؛ پیش‌فرض Release `pgpro-latest` در گیت‌هاب).

بیلد محلی (نیازمند Docker): `cd pgpro-site && docker compose -f docker-compose.yml -f docker-compose.local.yml up --build` ← `http://localhost:8080`

## فرم سفارش ← پنل postgis.ir
فرم صفحه‌ی `/order` با `fetch` به `https://postgis.ir/api/pgpro/lead/` می‌فرستد (کد: `core/pgpro_lead.py` در پنل).
درخواست در پنل مدیریت زیر «درخواست‌های تماس و جلسه» با موضوع «پایگاه داده مکانی پرو» ثبت و به مدیر اعلان می‌شود.
- مبدأهای مجاز با متغیر `PGPRO_SITE_ORIGINS` در پنل (پیش‌فرض `https://pgpro.ir,https://www.pgpro.ir`)
- محافظت: تله‌ی ربات (honeypot)، سقف ۵ درخواست در ساعت برای هر IP و ۳ در روز برای هر شماره
- اگر ارسال نشد، به فرم عمومی `postgis.ir/contact/?topic=pgpro` ارجاع می‌شود

## کانال به‌روزرسانی دستگاه‌ها (`/update/`)
nginx درخواست `https://pgpro.ir/update/<فایل>` را (`latest.json`، `pgpro-update-latest.tar.xz`، `.sha256`، `.sha256.sig`) با ۳۰۲ به Release گیت‌هاب
`pgpro-latest` می‌فرستد؛ پس بسته‌ی ۹۰ مگابایتی روی خود سایت نمی‌نشیند و انتشار بسته همان گردش‌کار فعلی ساخت ایمیج است.
برای اینکه دستگاه‌ها از pgpro.ir به‌روز شوند، در **شاخه‌ی `pgpro`** یک خط عوض می‌شود
(`image/overlay/rootfs/usr/local/sbin/pgpro-update`):
```diff
-UPDATE_BASE_URL=https://github.com/arazshah/postgis/releases/download/pgpro-latest
+UPDATE_BASE_URL=${PGPRO_UPDATE_URL:-https://pgpro.ir/update}
```
(`curl -L` در اسکریپت هدایت را دنبال می‌کند.) دستگاه‌هایی که ایمیج قدیمی دارند تا یک‌بار به‌روزرسانی نشوند همان نشانی گیت‌هاب را دارند.

## امنیت
CSP سخت (`default-src 'self'` و فقط `connect-src https://postgis.ir`)، بدون کوکی و بدون رهگیری، `read_only` و `no-new-privileges` در کانتینر.
