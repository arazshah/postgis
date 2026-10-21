---
title: REST API جدول‌ها چیست و چطور فیلتر کنم؟
summary: آدرس /rest/نام-سرویس/نام-جدول/ ردیف‌ها را به‌صورت JSON برمی‌گرداند. با limit (پیش‌فرض ۱۰۰، حداکثر ۱۰۰۰)، offset، order، bbox و فیلتر ستونی مثل col__gt=5 نتیجه را محدود کنید.
kind: reference
keywords: rest api, rest, json, فیلتر, limit, offset, order, bbox, col__gt, ilike, صفحه بندی, crud
related: rest-write-access, api-keys, ogc-api-features, field-form
featured: yes
order: 110
reviewed: 2026-10-21
---
## آدرس‌ها

| مسیر | کار |
|---|---|
| `/rest/<سرویس>/` | فهرست جدول‌های فعال |
| `/rest/<سرویس>/<جدول>/` | فهرست ردیف‌ها |
| `/rest/<سرویس>/<جدول>/<کلید>/` | یک ردیف |

جدول‌ها را باید در صفحه REST فعال کنید.

## پارامترها

| پارامتر | معنی |
|---|---|
| `limit` | تعداد ردیف (پیش‌فرض ۱۰۰، حداکثر ۱۰۰۰) |
| `offset` | صفحه‌بندی |
| `order` | ترتیب (نام ستون) |
| `bbox` | فیلتر مکانی (طول و عرض) |
| `col=v` | برابر |
| `col__gt`، `__gte`، `__lt`، `__lte`، `__ne` | مقایسه |
| `col__like` | جست‌وجوی متنی بدون حساسیت به حروف |

مثال: `/rest/demo/schools/?type=primary&students__gt=300&limit=20&order=name`

دسترسی با [کلید](kb:api-keys)؛ نوشتن: [REST write](kb:rest-write-access). اگر فقط خواندن استاندارد می‌خواهید، [OGC API](kb:ogc-api-features) را ببینید.
