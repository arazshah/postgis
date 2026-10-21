---
title: خطای «too many connections» یا «remaining connection slots»؛ چه کنم؟
summary: تعداد اتصال‌های هم‌زمان از سقف پلن ({{plan_connections}}) بیشتر شده است. برنامه وب باید از PgBouncer یا pool محدود استفاده کند و اتصال‌های باز و بی‌استفاده را ببندد.
kind: trouble
keywords: too many connections, connection limit, remaining connection slots, سقف اتصال, اتصال زیاد, pool, 53300
related: pgbouncer, connect-web-app-pooling, usage-and-performance
order: 40
reviewed: 2026-10-21
---
## چرا؟

هر اتصال باز (حتی بی‌کار) یک سهم از سقف {{plan_connections}} اتصال هم‌زمان را می‌گیرد. برنامه‌ای که برای هر درخواست اتصال جدید باز می‌کند و نمی‌بندد، سریع به سقف می‌رسد.

## راه‌حل

1. در برنامه از **pool** با اندازه کوچک (مثلاً ۳ تا ۵) استفاده کنید ([راهنما](kb:connect-web-app-pooling)).
2. اتصال [PgBouncer](kb:pgbouncer) را برای وب‌سایت بگذارید.
3. ابزارهای قدیمی (QGIS، pgAdmin) را که باز مانده‌اند ببندید.
4. در [مصرف](kb:usage-and-performance) تعداد اتصال را ببینید.
5. اگر واقعاً بیشتر لازم است، [پلن را ارتقا دهید](kb:upgrade-plan).
