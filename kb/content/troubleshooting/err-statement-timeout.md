---
title: خطای «canceling statement due to statement timeout»؛ کوئری من قطع می‌شود
summary: هر کوئری زمان مجاز دارد (در پلن شما {{plan_timeout}} ثانیه؛ در کنسول SQL سایت کوتاه‌تر است). کوئری طولانی را بهینه کنید (نمایه مکانی، فیلتر محدوده) یا آن را از اتصال مستقیم با ابزار دسکتاپ اجرا کنید.
kind: trouble
keywords: statement timeout, canceling statement, کوئری قطع شد, زمان کوئری, timeout کوئری, کند, 57014
related: sql-explain-performance, sql-console, spatial-index-gist, plans-overview
order: 50
reviewed: 2026-10-21
---
## زمان مجاز

- اتصال مستقیم: {{plan_timeout}} ثانیه (طبق پلن).
- [کنسول SQL](kb:sql-console) سایت: کوتاه‌تر (حدود ۲۰ ثانیه).

## چه کنم

1. **بهینه‌سازی**: [علت کندی](kb:sql-explain-performance) را با EXPLAIN بیابید؛ معمولاً نبود [نمایه مکانی](kb:spatial-index-gist) است.
2. **کم‌کردن حجم کار**: ابتدا با ST_Intersects محدوده را کوچک کنید.
3. **تقسیم کار**: عملیات سنگین را روی بخش‌های جدا اجرا کنید.
4. **ابزار دسکتاپ**: کار طولانی را با [psql یا pgAdmin](kb:connect-psql-pgadmin) و اتصال مستقیم اجرا کنید.
5. پلن بالاتر زمان بیشتر می‌دهد ([پلن‌ها](kb:plans-overview)).
