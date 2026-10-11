# ژئوپایگاه — پایگاه داده مکانی PostGIS به‌صورت سرویس

پنل فارسی برای ساخت پایگاه داده PostGIS آماده برای WebGIS، QGIS و GeoServer.
کاربر ثبت‌نام می‌کند، یک نام و رمز انتخاب می‌کند، افزونه‌ها را تیک می‌زند و اطلاعات اتصال را تحویل می‌گیرد.

## ساختار

| بخش | توضیح |
|---|---|
| `accounts/` | ورود و ثبت‌نام با موبایل و رمز یک‌بار مصرف (sms.ir)، محدودیت نرخ، پروفایل |
| `databases/models.py` | `DatabaseServer` (سرورهای مشتریان، فقط ادمین)، `Plan`، `Extension` (فهرست سفید)، `UserDatabase`، `ActivityLog` |
| `databases/provisioner.py` | ارتباط امن با PostgreSQL: ساخت نقش و دیتابیس هم‌نام، محدودیت‌ها، افزونه‌ها، فقط‌خواندنی، تعلیق، حذف |
| `databases/services.py` | منطق کسب‌وکار: ساخت، حذف، تمدید، پایش حجم، چرخه انقضا |
| `core/` | صفحه اصلی، آموزش‌ها، قوانین، `/healthz` |
| `templates/`, `static/` | رابط فارسی راست‌به‌چپ؛ فونت‌ها محلی و بدون CDN |

مدیریت در `/manage/` است. سرورهای دیتابیس مشتریان از بخش «سرورهای دیتابیس» اضافه می‌شوند؛ رمز ادمین سرور رمزنگاری‌شده ذخیره می‌شود و با هر ذخیره، اتصال خودکار آزمایش می‌شود. می‌توانید چند سرور تعریف کنید؛ دیتابیس جدید روی سرور پیش‌فرضِ فعال با ظرفیت آزاد ساخته می‌شود.

## اجرای محلی

```bash
pip install -r requirements-dev.txt
export DJANGO_DEBUG=1
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

یا با Docker و یک PostGIS آزمایشی: `docker compose -f docker-compose.dev.yml up --build`
سپس در `/manage/` سرور با host `tenant-pg`، پورت `5432`، کاربر `postgres` و رمز `devpass` اضافه کنید.

## تست

```bash
DJANGO_TESTING=1 python manage.py test                       # تست‌های واحد
DJANGO_TESTING=1 TEST_PG_HOST=localhost TEST_PG_PORT=5433 \
  TEST_PG_PASSWORD=devpass python manage.py test             # + تست روی PostGIS واقعی
ruff check .
```

در GitHub Actions هر Pull Request و هر push روی `main` این‌ها را اجرا می‌کند: lint، بررسی مایگریشن، تست‌ها روی PostGIS واقعی، ساخت ایمیج Docker و تست سلامت کانتینر.

## روال کار با گیت

1. هر تغییر روی یک شاخه جدا (`feature/...`) انجام می‌شود.
2. Pull Request به `main` باز می‌شود؛ CI باید سبز شود.
3. بعد از merge به `main`، Coolify خودکار دیپلوی می‌کند.

پیشنهاد: در GitHub برای `main` قانون Branch protection با «Require status checks to pass» (کار `test` و `docker`) فعال کنید.

## دیپلوی روی Coolify

1. **دیتابیس پنل:** در Coolify یک PostgreSQL بسازید (این فقط برای کاربران و تنظیمات پنل است، نه دیتابیس مشتریان) و Internal URL آن را بردارید.
2. **برنامه:** New Resource ← Public/Private Repository (GitHub App) ← همین ریپو، شاخه `main`، Build Pack: **Dockerfile**، پورت **8000**.
3. **دامنه:** مثلاً `https://postgis.ir` (رکورد A زیردامنه را به IP سرور Coolify بزنید).
4. **متغیرهای محیطی:** از `.env.example`؛ حداقل:
   - `DJANGO_SECRET_KEY`
   - `CREDENTIALS_ENCRYPTION_KEY` (یک بار بسازید و هرگز عوض نکنید، وگرنه رمزهای ذخیره‌شده سرورها خوانده نمی‌شوند)
   - `DATABASE_URL`
   - `DJANGO_ALLOWED_HOSTS=postgis.ir`
   - `DJANGO_CSRF_TRUSTED_ORIGINS=https://postgis.ir`
   - `DJANGO_SUPERUSER_PHONE`: موبایل ادمین؛ ورود به `/manage/` هم با رمز یک‌بار مصرف است
   - `SMSIR_API_KEY`، `SMSIR_TEMPLATE_ID` و `SMSIR_CODE_PARAM` (بخش پیامک را ببینید)
5. **Health check:** مسیر `/healthz`.
6. **دیپلوی خودکار:** با اتصال از طریق GitHub App، گزینه Auto Deploy را روشن کنید؛ هر push یا merge روی `main` دیپلوی می‌شود. اگر به‌جای GitHub App از Deploy Key استفاده می‌کنید، از تب Webhooks آدرس webhook و secret را بردارید و در GitHub ← Settings ← Webhooks با رویداد push اضافه کنید.
7. **کار زمان‌بندی‌شده:** در تب Scheduled Tasks:
   - دستور `python manage.py run_maintenance`
   - زمان‌بندی `*/10 * * * *`

   این کار حجم را می‌سنجد، دیتابیس‌های پر را فقط‌خواندنی می‌کند، انقضا را مدیریت می‌کند و سلامت سرورها را بررسی می‌کند.

مایگریشن‌ها در هر دیپلوی خودکار اجرا می‌شوند (`docker/entrypoint.sh`).

## پیامک (sms.ir)

1. در پنل sms.ir بخش توسعه‌دهندگان، یک **کلید API** بسازید. اگر محدودیت IP دارد، IP سرور Coolify را اضافه کنید.
2. در بخش «ارسال سریع / قالب‌ها» یک قالب کد تأیید بسازید، مثلاً:
   `کد ورود شما به پستجیس: #CODE#` و منتظر تأیید قالب بمانید.
3. شناسه قالب را در `SMSIR_TEMPLATE_ID` و نام متغیر (بدون #) را در `SMSIR_CODE_PARAM` بگذارید.
4. اختیاری: برای پیامک‌های هشدار حجم و انقضا، شماره خط را در `SMSIR_LINE_NUMBER` بگذارید.

قوانین امنیتی رمز یک‌بار مصرف (قابل تنظیم با متغیر محیطی):
- اعتبار کد: ۲ دقیقه
- فاصله ارسال دوباره: ۶۰ ثانیه
- حداکثر تلاش برای هر کد: ۵ بار
- سقف درخواست کد: ۵ بار در ساعت برای هر شماره و ۲۰ بار برای هر IP
- خود کد ذخیره نمی‌شود، فقط HMAC آن

در توسعه `SMS_BACKEND=console` است و کد در لاگ و روی صفحه نمایش داده می‌شود.

## آماده‌سازی سرور PostGIS مشتریان (مرحله بعد)

- PostgreSQL 16 یا 17 + PostGIS 3.4 به بالا، به همراه pgRouting
- `password_encryption = scram-sha-256` و SSL فعال
- در `pg_hba.conf` فقط این خط برای کاربران:
  ```
  hostssl  sameuser  all  0.0.0.0/0  scram-sha-256
  ```
  نام دیتابیس و نقش هر کاربر یکی است، پس هر کاربر فقط به دیتابیس خودش وصل می‌شود.
- یک خط جدا برای IP پنل با کاربر ادمین (superuser)
