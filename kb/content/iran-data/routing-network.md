---
title: «شبکه مسیریابی» چیست و چه جدول‌هایی می‌سازد؟
summary: گزینه شبکه مسیریابی جدول routing.ways (یال‌های شبکه با هزینه و جهت) و گره‌ها را می‌سازد تا با pgRouting کوتاه‌ترین مسیر و حوزه دسترسی بگیرید. فقط برای شهر یا شهرستان و روی سرورهایی که pgRouting دارند.
kind: concept
keywords: مسیریابی, routing, pgrouting, routing.ways, ways_vertices_pgr, شبکه معابر, گراف, یال, گره, topology
related: routing-shortest-path, service-area, what-is-pgrouting, osm-area-choice
order: 40
reviewed: 2026-10-21
---
## چه می‌سازد؟

- `routing.ways`: هر یال (قطعه جاده) با `source`، `target`، `cost`، `reverse_cost` و `length_m`.
- `routing.ways_vertices_pgr`: گره‌های تقاطع.

## محدودیت‌ها

- فقط برای **شهر یا شهرستان** (استان کامل برای گراف سنگین است).
- افزونه pgRouting باید روی سرور باشد؛ اگر نبود، پیام می‌بینید و می‌توانید [تیکت بزنید](kb:support-ticket) یا [افزونه را نصب کنید](kb:install-extension).
- مسیریابی بر اساس شبکه OSM است و محدودیت‌های لحظه‌ای (ترافیک، بسته بودن) را نمی‌داند.

بعد از ساخت: [کوتاه‌ترین مسیر](kb:routing-shortest-path)، [حوزه دسترسی](kb:service-area). آشنایی با pgRouting: [pgRouting چیست؟](kb:what-is-pgrouting)
