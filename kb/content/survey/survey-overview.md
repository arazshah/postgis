---
title: برداشت میدانی چیست و برای چه کسی است؟
summary: بخشی برای نقشه‌برداران: نقطه، خط و چندضلعی را با GPS گوشی یا گیرنده دقیق RTK برداشت کنید، حتی بدون اینترنت. داده مستقیم در جدول‌های PostGIS خودتان می‌نشیند و بقیه امکانات سایت رویش کار می‌کند.
kind: concept
keywords: برداشت میدانی, نقشه برداری, GNSS, GPS, RTK, نقطه برداری, survey, کاداستر, توپوگرافی
related: survey-first-project, survey-data-tables, survey-phone-gps, survey-external-receiver
featured: yes
order: 10
reviewed: 2026-10-25
---
**برداشت میدانی** یک فضای کار کامل برای ثبت داده در میدان است. از منوی کنار پایگاه داده «برداشت میدانی» را باز کنید.

## چه کارهایی می‌شود کرد

- برداشت **نقطه، خط و چندضلعی** با [GPS گوشی](kb:survey-phone-gps) یا [گیرنده خارجی](kb:survey-external-receiver)
- دریافت تصحیح [RTK از کستر NTRIP](kb:survey-ntrip-rtk)
- [کار بدون اینترنت](kb:survey-offline) و ارسال بعدی، با [نقشه آفلاین](kb:survey-offline-basemap)
- [ورود نقاط از فایل و خروجی DXF، CSV، GeoJSON و گزارش چاپی](kb:survey-import-export)
- [فاصله، آزیموت، مساحت و پیاده‌سازی نقطه](kb:survey-cogo-stakeout)
- [سطح TIN، منحنی میزان و حجم خاکبرداری](kb:survey-surface-contours)

## چرا با ابزارهای دیگر فرق دارد

داده برداشت‌شده یک **جدول معمولی PostGIS** در پایگاه داده خودتان است؛ نه فایل بسته. پس همان لحظه در [QGIS](kb:connect-qgis)، [مرورگر داده](kb:explorer-overview)، [نقشه چندلایه](kb:multi-layer-maps) و [REST API](kb:rest-api-overview) هم دیده می‌شود. ساختار جدول‌ها در [داده برداشت در پایگاه داده](kb:survey-data-tables) آمده است.

## چه چیزی لازم است

- یک مرورگر مدرن (برای گیرنده خارجی: Chrome یا Edge)
- ویرایشگر یا مالک پایگاه داده بودن برای ثبت داده؛ بیننده فقط می‌بیند
- سهمیه پروژه و نقطه در پلن: [سهمیه و پلن برداشت](kb:survey-quota)

> اگر منوی «برداشت میدانی» را نمی‌بینید، این بخش هنوز برای سایت فعال نشده است؛ از [پشتیبانی](kb:support-ticket) بپرسید.
