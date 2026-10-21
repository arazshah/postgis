---
title: چطور از QGIS به پایگاه داده PostGIS وصل شوم و لایه‌ها را ببینم؟
summary: در پنل Browser روی PostgreSQL راست‌کلیک و New Connection را بزنید، Host، Port و Database را از صفحه پایگاه داده کپی کنید، SSL mode را روی require بگذارید، نام کاربری و رمز را با Store وارد و Test Connection بزنید.
kind: howto
keywords: qgis, کیوجیس, اتصال qgis, new connection, postgresql, browser, test connection, لایه, اضافه کردن لایه
related: connection-info, err-connection-refused, err-password-auth, err-ssl-off, import-qgis-db-manager
featured: yes
order: 10
reviewed: 2026-10-21
---
## افزودن اتصال

نسخه ۳٫۲۸ یا جدیدتر QGIS پیشنهاد می‌شود.

1. در پنل **Browser** روی **PostgreSQL** راست‌کلیک و **New Connection…** را بزنید.
2. در **Name** یک نام دلخواه بنویسید.
3. **Host**، **Port** و **Database** را از صفحه پایگاه داده کپی کنید ([اطلاعات اتصال](kb:connection-info)). پورت معمول 5432 نیست.
4. **SSL mode** را روی `require` بگذارید.
5. در بخش **Authentication** زبانه **Basic** را باز کنید، نام کاربری و رمز را وارد و تیک **Store** را بزنید.
6. **Test Connection** را بزنید؛ با پیام موفقیت **OK** کنید.

## نمایش لایه

اتصال را در Browser باز کنید، به schema به نام `public` بروید و جدول را روی نقشه بکشید.

## خطاهای رایج

| پیام | راه‌حل |
|---|---|
| `Connection refused` | پورت اشتباه است؛ [راهنما](kb:err-connection-refused) |
| `password authentication failed` | نام کاربری یا رمز اشتباه است؛ [راهنما](kb:err-password-auth) |
| `no pg_hba.conf entry … SSL off` | SSL mode را `require` کنید؛ [راهنما](kb:err-ssl-off) |
| `too many connections for role` | اتصال‌های باز زیاد است؛ [راهنما](kb:err-too-many-connections) |
| `canceling statement due to statement timeout` | [راهنما](kb:err-statement-timeout) |

!!! tip "نکته"
    اگر لایه‌ای نمایش داده نشد، [SRID و نمایه](kb:err-layer-shifted) را بررسی کنید. برای نمایش لایه‌ی بزرگ‌تر از ۲٬۰۰۰ عارضه، QGIS بهتر از پیش‌نمایش سایت است ([محدودیت نقشه](kb:explorer-map-limit)).
