---
title: لایه‌ام در QGIS یا نقشه جابه‌جا یا در جای اشتباه (مثلاً وسط اقیانوس) است؛ چرا؟
summary: تقریباً همیشه SRID اشتباه یا صفر است یا مختصات بدون تبدیل برچسب خورده. SRID واقعی را مشخص و با ST_Transform تبدیل کنید؛ ST_SetSRID فقط برچسب را عوض می‌کند. همچنین ترتیب lon/lat را بسنجید.
kind: trouble
keywords: لایه جابجا شد, اقیانوس, srid اشتباه, مختصات اشتباه, لایه نمایش داده نمی شود در جای درست, 0,0, خلیج گینه, lon lat جابجا
related: sql-transform-srid, what-is-srid, which-srid-for-iran, data-health, import-csv-points
featured: yes
order: 60
reviewed: 2026-10-21
---
## نشانه‌ها و علت

| نشانه | علت محتمل |
|---|---|
| نقاط نزدیک (0,0) در اقیانوس اطلس | مختصات UTM به‌عنوان درجه خوانده شده یا SRID صفر است |
| لایه چند صد کیلومتر یا چند ناحیه جابه‌جاست | سیستم مختصات اشتباه (ناحیه UTM یا datum) |
| نقاط در جای بسیار دور، آینه‌ای | lon و lat جابه‌جا ([CSV](kb:import-csv-points)) |
| لایه اصلاً دیده نمی‌شود | SRID تعریف‌نشده (0) |

## بررسی و رفع

```sql
SELECT Find_SRID('public', 'mytable', 'geom');
SELECT ST_AsText(geom) FROM mytable LIMIT 3;
```

- مقادیر عددی ۴۴ تا ۶۳ و ۲۵ تا ۴۰ یعنی درجه (4326)؛ مقادیر صدها هزار یعنی متری (UTM) ([SRID](kb:what-is-srid)).
- SRID درست مشخص است ولی صفر ثبت شده: ابتدا `ST_SetSRID` و سپس `ST_Transform` ([راهنما](kb:sql-transform-srid)).
- در [سلامت داده](kb:data-health) گزینه «تعیین SRID» هست.
- برای ایران: [کدام SRID؟](kb:which-srid-for-iran)
