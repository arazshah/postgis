---
title: چطور افزونه جدید (مثل pgRouting یا pg_trgm) نصب کنم؟
summary: در صفحه پایگاه داده «افزونه‌ها» را باز کنید، افزونه مجاز پلن خود را انتخاب و نصب کنید. افزونه‌هایی که در پلن شما مجاز نیستند نصب نمی‌شوند؛ برای آن‌ها ارتقا یا تیکت لازم است.
kind: howto
keywords: نصب افزونه, extension, create extension, pgrouting, pg_trgm, postgis_raster, افزونه مجاز, افزودن افزونه
related: choose-extensions, postgis-extensions-explained, upgrade-plan, support-ticket
order: 60
reviewed: 2026-10-21
---
1. صفحه پایگاه داده ← **افزونه‌ها**.
2. از فهرست مجاز، افزونه را انتخاب و «نصب» را بزنید.

- فهرست از **پلن** شما می‌آید؛ اگر افزونه‌ای نیست، [ارتقا](kb:upgrade-plan) یا [تیکت](kb:support-ticket) بزنید.
- معرفی افزونه‌ها: [توضیح افزونه‌ها](kb:postgis-extensions-explained) و [انتخاب هنگام ساخت](kb:choose-extensions).
- برای pgRouting، روی سرور هم باید موجود باشد ([شبکه مسیریابی](kb:routing-network)).
- با SQL (`CREATE EXTENSION`) فقط افزونه‌های مجاز و قابل‌اعتماد کار می‌کند؛ راه رسمی همین صفحه است.
