---
title: «حوزه دسترسی» (isochrone) چیست و چطور بسازم؟
summary: محدوده‌ای که از یک نقطه با پیمودن فاصله مشخص روی شبکه معابر می‌رسید (مثلاً ۱ کیلومتر پیاده‌روی). ابزار «حوزه دسترسی» در بخش تحلیل آن را روی شبکه مسیریابی می‌سازد.
kind: howto
keywords: حوزه دسترسی, isochrone, service area, دسترسی, محدوده قابل دسترس, pgr_drivingdistance, پیاده, ۵ دقیقه
related: routing-network, analysis-tools, routing-shortest-path
order: 60
reviewed: 2026-10-21
---
## تفاوت با بافر

بافر ۵۰۰ متری دایره‌ای است؛ حوزه دسترسی فقط جاهایی را می‌گیرد که **روی جاده‌ها** تا ۵۰۰ متر می‌رسید و واقعیت‌تر است.

## مراحل

1. [شبکه مسیریابی](kb:routing-network) را وارد کنید.
2. در بخش تحلیل «حوزه دسترسی» را انتخاب کنید ([ابزارها](kb:analysis-tools)).
3. لایه نقطه‌های مبدأ و فاصله را بدهید؛ خروجی جدول چندضلعی‌هاست.

## با SQL

```sql
SELECT * FROM pgr_drivingDistance(
  'SELECT gid AS id, source, target, length_m AS cost FROM routing.ways',
  12345, 1000, false);
```

عدد ۱۲۳۴۵ شناسه گره شروع و ۱۰۰۰ فاصله به متر است. گره شروع را مانند [کوتاه‌ترین مسیر](kb:routing-shortest-path) پیدا کنید.
