---
title: حالت SSL را روی چه گزینه‌ای بگذارم و require یعنی چه؟
summary: روی require بگذارید. اتصال بدون SSL پذیرفته نمی‌شود و با خطای no pg_hba.conf entry روبه‌رو می‌شوید. require اتصال را رمزنگاری می‌کند و نیازی به فایل گواهی ندارید.
kind: faq
keywords: ssl, sslmode, require, disable, prefer, رمزنگاری, گواهی, certificate, tls
related: err-ssl-off, connection-info, is-connection-secure
order: 80
reviewed: 2026-10-21
---
## گزینه‌ها

| sslmode | معنی | برای ما |
|---|---|---|
| `disable` | بدون رمزنگاری | **کار نمی‌کند** |
| `prefer` | اول SSL، در صورت نشدن بدون SSL | معمولاً کار می‌کند ولی رمزنگاری را تضمین نمی‌کند؛ توصیه نمی‌شود |
| `require` | حتماً SSL | **توصیه‌شده** |

## چرا require؟

سرور اتصال بدون SSL را قبول نمی‌کند، و `require` بدون نیاز به گواهی خاصی اتصال را رمزنگاری می‌کند. در ابزارهایی که فیلد جدا برای SSL دارند (QGIS، GeoServer، pgAdmin، DBeaver)، `require` (در GeoServer با حروف بزرگ `REQUIRE`) را انتخاب کنید.

اگر خطای `no pg_hba.conf entry ... SSL off` دیدید: [راه‌حل](kb:err-ssl-off).
