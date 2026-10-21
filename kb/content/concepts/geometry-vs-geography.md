---
title: تفاوت geometry و geography در PostGIS چیست و کدام را انتخاب کنم؟
summary: geometry روی صفحه تخت (واحد سیستم مختصات) محاسبه می‌کند و همه توابع را دارد؛ geography روی کره زمین است و فاصله و مساحت را به متر می‌دهد ولی توابع کمتری دارد. برای ذخیره geometry را بگیرید و برای اندازه‌گیری به متر موقتاً به geography تبدیل کنید.
kind: concept
keywords: geometry, geography, فاصله به متر, مساحت, تبدیل, cast, ::geography
related: what-is-srid, sql-distance-meters, sql-area-length, which-srid-for-iran
order: 40
reviewed: 2026-10-21
---
## تفاوت

| | `geometry` | `geography` |
|---|---|---|
| فضای محاسبه | صفحه تخت | سطح کره (بیضوی) زمین |
| واحد فاصله و مساحت | واحد سیستم مختصات (درجه برای 4326!) | متر و متر مربع |
| توابع | همه توابع PostGIS | فقط بخشی از توابع |
| سرعت | سریع‌تر | کندتر |

## نکته مهم: فاصله در 4326 به درجه است

اگر داده در EPSG:4326 باشد، `ST_Distance` روی geometry عددی «به درجه» می‌دهد که برای کاربرد عملی بی‌معنی است. دو راه درست:

```sql
-- راه ۱: تبدیل موقت به geography (ساده‌ترین)
SELECT ST_Distance(a.geom::geography, b.geom::geography) AS meters
FROM a, b;

-- راه ۲: تبدیل به UTM مناطق ایران (مثلاً تهران 32639)
SELECT ST_Distance(ST_Transform(a.geom, 32639), ST_Transform(b.geom, 32639)) AS meters
FROM a, b;
```

## توصیه

- ذخیره: `geometry` با SRID اصلی داده.
- اندازه‌گیری (فاصله، بافر، مساحت): با `::geography` یا تبدیل به UTM.
- برای نمایه سریع روی geography، باید نمایه‌ای روی همان عبارت بسازید؛ در عمل بسیاری از جدول‌ها فقط نمایه geometry دارند.

جزئیات بیشتر: [SRID چیست؟](kb:what-is-srid) · [فاصله به متر](kb:sql-distance-meters) · [مساحت و طول](kb:sql-area-length)
