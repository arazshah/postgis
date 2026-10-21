---
title: هر افزونه PostGIS (pgRouting، رستر، توپولوژی، SFCGAL، pg_trgm، hstore، ...) چه کاری می‌کند؟
summary: PostGIS هسته مکانی است؛ pgRouting مسیریابی، رستر تصاویر ماهواره‌ای، توپولوژی مرز مشترک، SFCGAL هندسه سه‌بعدی، pg_trgm و fuzzystrmatch جست‌وجوی تقریبی متن، hstore ویژگی‌های متغیر و uuid-ossp شناسه یکتا می‌دهند.
kind: reference
keywords: افزونه ها, extensions, pgrouting, postgis_raster, topology, sfcgal, fuzzystrmatch, pg_trgm, hstore, uuid-ossp
related: choose-extensions, install-extension, what-is-pgrouting, vector-vs-raster
order: 120
reviewed: 2026-10-21
---
## توضیح هر افزونه

- **PostGIS:** geometry و geography، توابع `ST_`، نمایه مکانی. همیشه نصب می‌شود.
- **pgRouting:** کوتاه‌ترین مسیر و تحلیل شبکه ([توضیح](kb:what-is-pgrouting)).
- **postgis_raster:** ذخیره و تحلیل رستر؛ حجم زیادی می‌گیرد ([رستر](kb:vector-vs-raster)).
- **postgis_topology:** مدیریت همسایگی و مرز مشترک؛ مناسب کاداستر.
- **postgis_sfcgal:** عملیات سه‌بعدی و هندسه دقیق.
- **pg_trgm:** جست‌وجوی سریع `LIKE` و تشابه متنی روی نام عوارض.
- **fuzzystrmatch:** شباهت کلمات؛ مفید برای نشانی و نام مکان.
- **hstore:** ذخیره ویژگی‌های متغیر؛ رایج در داده OpenStreetMap.
- **uuid-ossp:** تولید شناسه یکتای جهانی.

## نصب

هنگام ساخت یا بعداً: [نصب افزونه](kb:install-extension). فهرست مجاز هر پلن ممکن است متفاوت باشد؛ در صفحه پایگاه داده، کادر «افزونه‌های نصب‌شده» را ببینید.
