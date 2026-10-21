---
title: PgBouncer چیست و کی باید از آن استفاده کنم؟
summary: PgBouncer اتصال‌های برنامه را جمع می‌کند تا از سقف اتصال پلن ({{plan_connections}} اتصال هم‌زمان) عبور نکنید. برای وب‌سایت‌ها و برنامه‌ها از اتصال PgBouncer استفاده کنید؛ برای QGIS، pg_dump و کارهای مدیریتی از اتصال مستقیم.
kind: concept
keywords: pgbouncer, connection pool, تجمیع اتصال, too many connections, اتصال وب سایت, پورت pgbouncer, transaction mode
related: connect-web-app-pooling, err-too-many-connections, connection-info
order: 120
reviewed: 2026-10-21
---
## دو اتصال

| اتصال | برای |
|---|---|
| مستقیم | QGIS، pgAdmin، pg_dump، ogr2ogr |
| PgBouncer (پورت جدا) | وب‌سایت و برنامه با ترافیک زیاد |

## محدودیت‌های حالت transaction

در PgBouncer دستورهای وابسته به نشست مثل `LISTEN`، `SET` خارج از تراکنش و جدول موقت میان تراکنش‌ها کار نمی‌کنند. در درایور، prepared statement سمت سرور را خاموش یا مطابق تنظیمات درایور تنظیم کنید.

راهنمای کامل برنامه وب: [اتصال وب با pool](kb:connect-web-app-pooling). خطای زیاد بودن اتصال: [راه‌حل](kb:err-too-many-connections). اگر گزینه PgBouncer در اطلاعات اتصال دیده نمی‌شود، روی سرور شما فعال نیست؛ [تیکت](kb:support-ticket) بزنید.
