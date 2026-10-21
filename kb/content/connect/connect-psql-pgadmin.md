---
title: چطور با psql، pgAdmin یا DBeaver به پایگاه داده وصل شوم؟
summary: هر سه با همان اطلاعات اتصال کار می‌کنند: میزبان، پورت، پایگاه داده، کاربر و رمز، و حالت SSL روی require. psql را با یک رشته اتصال اجرا کنید و در pgAdmin یا DBeaver یک Server یا Connection جدید از نوع PostgreSQL بسازید.
kind: howto
keywords: psql, pgadmin, dbeaver, مدیریت پایگاه داده, ترمینال, sql client, اتصال, datagrip
related: connection-info, connection-string-formats, ssl-modes, sql-console
order: 60
reviewed: 2026-10-21
---
## psql

```bash
psql "host=HOST port=PORT dbname=DB user=USER sslmode=require"
```

رمز را وقتی پرسید وارد کنید. بعد از اتصال `\dt` جدول‌ها و `SELECT PostGIS_Version();` نسخه PostGIS را نشان می‌دهد.

## pgAdmin

1. روی Servers راست‌کلیک: **Register › Server**.
2. در زبانه **Connection**: Host، Port، Maintenance database (نام پایگاه داده‌تان)، Username و Password.
3. در زبانه **SSL**، حالت `require`.

## DBeaver

یک اتصال جدید از نوع PostgreSQL بسازید، Host و Port و Database و کاربر و رمز را بدهید و در بخش SSL حالت `require` را انتخاب کنید.

!!! tip "بدون نصب هیچ‌چیز"
    برای کوئری ساده می‌توانید از [کنسول SQL داخل سایت](kb:sql-console) استفاده کنید.
