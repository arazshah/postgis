---
title: چطور GeoServer را به پایگاه داده وصل کنم و لایه را منتشر کنم؟
summary: در GeoServer از Stores، Add new Store و PostGIS استفاده کنید؛ host، port، database، user و passwd را از زبانه GeoServer صفحه پایگاه داده بردارید، schema را public، SSL را REQUIRE و max connections را ۳ بگذارید؛ بعد کنار جدول Publish بزنید.
kind: howto
keywords: geoserver, ژئوسرور, store, workspace, postgis store, wms, wfs, max connections, geowebcache, انتشار لایه
related: connection-info, wms-wfs-qgis-server, database-users, enterprise-geoserver
order: 20
reviewed: 2026-10-21
---
## ساخت Store

1. در GeoServer به **Stores › Add new Store** بروید و **PostGIS** را انتخاب کنید.
2. یک Workspace انتخاب و برای Store نام بگذارید.
3. مقادیر `host`، `port`، `database`، `user` و `passwd` را از **زبانه GeoServer** صفحه پایگاه داده کپی کنید.
4. `schema` را `public` بگذارید.
5. **SSL mode** را روی `REQUIRE` بگذارید.
6. `max connections` را **۳** و `min connections` را **۱** بگذارید تا از سقف اتصال پلن ({{plan_connections}} اتصال همزمان در پلن {{plan_name}}) عبور نکنید.
7. **Save** را بزنید.

## انتشار لایه

بعد از ذخیره، فهرست جدول‌ها نمایش داده می‌شود. کنار جدول **Publish** را بزنید، در بخش Bounding Boxes روی **Compute from data** کلیک و ذخیره کنید. لایه حالا با WMS و WFS در دسترس است.

!!! tip "برای WebGIS پرترافیک"
    کش کاشی (GeoWebCache) را فعال کنید تا هر بار به پایگاه داده درخواست نرود.

## بهتر است با کاربر محدود وصل شوید

رمز اصلی پایگاه داده را در GeoServer نگذارید؛ برای آن [کاربر فقط‌خواندنی جدا بسازید](kb:database-users).

## جایگزین‌ها

- بدون نصب GeoServer: [WMS و WFS با QGIS Server](kb:wms-wfs-qgis-server).
- GeoServer کامل و اختصاصی روی سرور ما (پلن سازمانی): [GeoServer اختصاصی](kb:enterprise-geoserver).
