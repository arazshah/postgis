# نقشه‌ی راه ۹۰ روزه‌ی بازاریابی و درآمد (پوستر A1)

- `roadmap-a1.pdf`: نسخه‌ی چاپ؛ برداری، یک برگ A1 (۵۹۴×۸۴۱ میلی‌متر)، بدون حاشیه. همین را به چاپخانه بدهید.
- `roadmap-a1.png`: پیش‌نمایش ۱۵۰ dpi (۳۵۰۸×۴۹۶۱).
- `roadmap-a1.html`: متن و طراحی پوستر (توکن‌های رنگ و فونت‌های خود سایت، آیکون‌های `core/icons.py`).

ساخت دوباره بعد از ویرایش متن (Chromium و Playwright لازم است):

```bash
node docs/marketing/build.js        # PNG با ۱۵۰ dpi و PDF
node docs/marketing/build.js 300    # PNG با ۳۰۰ dpi
```

اگر متن بلندتر شد و از قاب بیرون زد، `build.js` پیام «سرریز» می‌دهد.
