# ساخت ویدیوهای راهنما

همه‌ی ویدیوهای مرکز راهنما (`static/help/video/<slug>.mp4` و پوستر `<slug>.jpg`) با این ابزار ساخته می‌شوند: بی‌کلام، با موسیقی،
۱۹۲۰×۱۰۸۰، قالب یکدست (کارت آغاز با شماره‌ی بخش، عنوان، خلاصه و مراحل؛ نوار مرحله‌ی شماره‌دار؛ کارت پایان با «بخش بعد»).
هر ویدیو یک سناریوی Playwright روی رابط واقعی سایت است (پایگاه نمایشی sqlite + سرور PostGIS محلی).

```bash
export NODE_PATH=$(npm root -g)                 # playwright
docs/help-video/build.sh <slug>                 # یک ویدیو؛ سناریو: scenarios/<slug>.js
docs/help-video/buildq.sh a b c                 # چند ویدیو پشت‌سرهم (گزارش در /tmp/vq-<slug>.log)
PORT=8766 PG_PORT=5433 docs/help-video/buildq.sh d e   # صف دوم همزمان (کلاستر PostgreSQL جدا)
docs/help-video/compress.sh                     # حدود نصف حجم برای مخزن
python docs/help-video/sync_seconds.py          # مدت واقعی ویدیو ← core/help.py
python docs/help-video/link_kb.py               # پیوند ویدیو در مقاله‌های پایگاه دانش
```

پیش‌نیاز: PostgreSQL با PostGIS (و UTF8)، `ffmpeg`، `gdal-bin`، `numpy` (موسیقی). `build.sh` خودش داده‌ی نمایشی (`demo.py init`)،
سرور وب، worker پس‌زمینه (ورود فایل، تحلیل، بکاپ) و در صورت نیاز سرویس ساختگی دستیار (`fake_llm.py`) را بالا می‌آورد.

- `scenarios/<slug>.js`: صحنه‌ها؛ متن مرحله‌ها با `step(...)` (باید با مراحل `core/help.py` هم‌خوان باشد)
- `demo.py`: داده‌ی نمایشی، پلن‌ها، سرور و داده‌ی بین صحنه‌ها (`init main|classroom-teacher|classroom-student`)
- `record.js` / `overlay.js`: ابزارهای صحنه (مکان‌نما، هایلایت، کارت‌ها)؛ `music.py`: موسیقی ملایم
- هشدارهای `WARN` در گزارش یعنی انتخابگری در رابط پیدا نشده؛ سناریو را اصلاح و ویدیو را دوباره بسازید

پس از تغییر رابط یک بخش، ویدیوی همان بخش را دوباره بسازید و `sync_seconds.py` را اجرا کنید.
