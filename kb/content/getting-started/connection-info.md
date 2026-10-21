---
title: اطلاعات اتصال به پایگاه داده را از کجا بردارم و هر مورد یعنی چه؟
summary: در صفحه پایگاه داده، میزبان (Host)، پورت (Port)، نام پایگاه داده و نام کاربری را با دکمه «کپی» بردارید. پورت سرور ما 5432 نیست و SSL را روی require بگذارید. رمز همان است که هنگام ساخت دیدید.
kind: howto
keywords: host, port, میزبان, پورت, رشته اتصال, connection string, اطلاعات اتصال, ssl, sslmode, 5432
related: connect-qgis, connection-string-formats, err-connection-refused, ssl-modes
featured: yes
order: 80
reviewed: 2026-10-21
---
## کجا ببینم؟

در «پایگاه‌های داده من» روی نام پایگاه داده یا «اطلاعات اتصال» بزنید. جدولی با این مقادیر می‌بینید؛ کنار هر کدام دکمه «کپی» است.

| مورد | معنی |
|---|---|
| **میزبان (Host)** | آدرس سرور پایگاه داده |
| **پورت (Port)** | شماره پورت اتصال؛ **پورت معمول PostgreSQL (5432) نیست** و باید دقیقاً از جدول کپی شود |
| **پایگاه داده (Database)** | مثلاً `gp_tehran_gis` |
| **نام کاربری (User)** | مثلاً `gp_tehran_gis_user` |
| **رمز عبور** | همان رمزی که هنگام ساخت دیدید ([گم شد؟](kb:password-shown-once)) |
| **SSL** | روی `require` بگذارید تا اتصال رمزنگاری شود |

## هنگام کپی چه نکته‌ای هست؟

گاهی هنگام کپی از صفحه فارسی یک نویسه نامرئی همراه رشته اتصال می‌آید. بهتر است از دکمه «کپی» استفاده کنید، نه انتخاب با ماوس.

## بعدش چه؟

برای هر نرم‌افزار راهنمای جدا هست: [QGIS](kb:connect-qgis)، [GeoServer](kb:connect-geoserver)، [ArcGIS Pro](kb:connect-arcgis-pro)، [پایتون](kb:connect-python)، [Node.js](kb:connect-nodejs). اگر خطا گرفتید: [Connection refused](kb:err-connection-refused).
