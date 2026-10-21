---
title: رشته اتصال (connection string) در قالب‌های مختلف چطور نوشته می‌شود؟
summary: قالب کلید-مقدار libpq، آدرس postgresql://، قالب SQLAlchemy، JDBC و ogr2ogr همگی از همان پنج مقدار اتصال و sslmode=require استفاده می‌کنند. نویسه‌های خاص رمز را در URL کدگذاری کنید.
kind: reference
keywords: connection string, رشته اتصال, uri, jdbc, sqlalchemy, libpq, url encode, رمز با کاراکتر خاص
related: connection-info, connect-python, connect-nodejs, ssl-modes
order: 70
reviewed: 2026-10-21
---
## قالب‌ها

| کاربرد | قالب |
|---|---|
| libpq / psql / psycopg | `host=HOST port=PORT dbname=DB user=USER password=PASS sslmode=require` |
| URI | `postgresql://USER:PASS@HOST:PORT/DB?sslmode=require` |
| SQLAlchemy | `postgresql+psycopg2://USER:PASS@HOST:PORT/DB?sslmode=require` |
| JDBC | `jdbc:postgresql://HOST:PORT/DB?sslmode=require` |
| ogr2ogr | `PG:"host=HOST port=PORT dbname=DB user=USER password=PASS sslmode=require"` |

## رمز با نویسه‌های خاص

در قالب URI، نویسه‌هایی مثل `@`، `:`، `/`، `?` و `#` در رمز باید کدگذاری شوند (مثلاً `@` ← `%40`). ساده‌ترین راه، قالب کلید-مقدار یا ساختن رمز بدون این نویسه‌هاست؛ دکمه «رمز تصادفی» رمز را فقط از حروف و عدد می‌سازد.

## مقدارها از کجا؟

همه از [اطلاعات اتصال](kb:connection-info) صفحه پایگاه داده. دکمه «کپی» را به انتخاب با ماوس ترجیح دهید ([نویسه نامرئی](kb:connection-info)). در صفحه پایگاه داده، زبانه‌های «رشته اتصال»، Python، psql و ... نمونه آماده با اطلاعات خود شما دارند.
