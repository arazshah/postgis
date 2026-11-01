# ساخت ویدیوهای راهنما

ویدیوهای `classroom-teacher` و `classroom-student` با این ابزار ساخته شده‌اند (بی‌کلام، با موسیقی، مثل ویدیوهای قبلی).
هر کدام یک سناریوی Playwright روی یک پایگاه نمایشی sqlite است؛ نه به سرور PostGIS نیاز دارد و نه به داده‌ی واقعی.

```bash
export NODE_PATH=$(npm root -g)          # playwright
docs/help-video/build.sh teacher classroom-teacher
docs/help-video/build.sh student classroom-student
```

خروجی `static/help/video/<slug>.mp4` (۱۹۲۰×۱۰۸۰) و `<slug>.jpg` (پوستر ۱۲۸۰×۷۲۰) است. سپس `seconds` همان راهنما را در `core/help.py` با مدت ویدیو یکی کنید.

- `demo.py`: داده‌ی نمایشی و سرور (ساخت پایگاه داده‌ی دانشجو در آن جعلی است)
- `record.js`: سناریوی هر ویدیو؛ متن مرحله‌ها با `step(...)`
- `overlay.js`: مکان‌نما، نوار مرحله، کارت عنوان و هایلایت
- `music.py`: موسیقی ملایم بی‌کلام

پس از تغییر رابط کلاس، ویدیو را دوباره بسازید.
