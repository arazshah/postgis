---
title: برنامه وب من با تعداد اتصال زیاد باز می‌کند؛ چطور از سقف اتصال همزمان عبور نکنم؟
summary: از connection pool با حداکثر ۳ اتصال استفاده کنید و اتصال‌ها را ببندید. برای وب‌سایت‌ها و APIهایی که اتصال کوتاه و زیاد باز می‌کنند، پورت PgBouncer (در صورت فعال بودن) صدها اتصال را با چند اتصال واقعی سرویس می‌دهد.
kind: howto
keywords: connection pool, pool, اتصال همزمان, too many connections, pgbouncer, max connections, برنامه وب, django, express
related: err-too-many-connections, pgbouncer, connect-python, connect-nodejs
order: 90
reviewed: 2026-10-21
---
## قاعده

سقف پلن {{plan_name}} {{plan_connections}} اتصال همزمان است (QGIS، GeoServer، pgAdmin و برنامه شما همه از همین سهم می‌خورند). پس:

- در برنامه وب از یک **pool** با حداکثر **۳** اتصال استفاده کنید.
- در GeoServer `max connections` را ۳ بگذارید ([راهنما](kb:connect-geoserver)).
- اتصال‌های بلااستفاده (QGIS و pgAdmin باز مانده) را ببندید.

## PgBouncer

اگر برنامه‌تان کوتاه‌مدت و زیاد وصل می‌شود (وب‌سایت، API، کارهای زمان‌بندی‌شده)، از اتصال **PgBouncer** استفاده کنید: در صفحه پایگاه داده کادر «اتصال برای وب‌سایت و برنامه‌ها (PgBouncer)» پورت جدایی نشان می‌دهد. جزئیات و محدودیت‌ها: [PgBouncer](kb:pgbouncer).

!!! warning "QGIS و pgAdmin"
    این‌ها را با پورت معمولی وصل کنید؛ PgBouncer برای برنامه‌هاست.
