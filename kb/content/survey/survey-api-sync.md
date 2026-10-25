---
title: چطور از برنامه خودم داده برداشت را با API بفرستم؟
summary: با یک کلید API دارای اجازه نوشتن، آیتم‌های JSON را به آدرس /api/v1/survey/نام-پروژه/sync/ POST کنید (تا ۱۰۰۰ آیتم در هر درخواست). ارسال تکراری با client_uuid ردیف دوباره نمی‌سازد و خطای هر آیتم جدا گزارش می‌شود.
kind: reference
keywords: api برداشت, sync, client_uuid, کلید api, ارسال نقطه, برنامه میدانی, post
related: api-keys, rest-write-access, survey-data-tables, survey-quota
order: 130
reviewed: 2026-10-25
---
## درخواست

```http
POST /api/v1/survey/<نام-پروژه>/sync/
Authorization: Bearer gpk_...
Content-Type: application/json

{"items": [
  {"kind": "point",
   "client_uuid": "8d1f0c1e-6f0a-4a9e-9f3c-2d6b1a7e5c10",
   "srid": 4326,
   "geometry": {"type": "Point", "coordinates": [51.389, 35.689]},
   "properties": {"pt_no": "12", "code": "GR", "h_ortho": 1189.4, "acc_h": 0.02}}
]}
```

- `<نام-پروژه>` همان schema پروژه است ([ساختار](kb:survey-data-tables)).
- کلید باید **اجازه نوشتن** داشته باشد: [ساخت کلید](kb:api-keys).
- `kind` می‌تواند `point`، `line`، `polygon` یا `session` باشد. حذف نرم با `"op": "delete"`.
- `srid` یا ۴۳۲۶ است یا SRID پروژه؛ ۴۳۲۶ روی سرور به SRID پروژه تبدیل می‌شود.

## پاسخ

برای هر آیتم `{client_uuid, status}` برمی‌گردد: `ok`، `duplicate` (قبلاً ثبت شده)، `missing` (برای حذف) یا `error` با `code` مثل `quota`، `geometry`، `srid`.

## خطاهای کلی

| وضعیت | معنی |
|---|---|
| 401 | کلید نیست یا نامعتبر است |
| 403 | کلید فقط خواندنی است یا پایگاه داده فقط‌خواندنی شده |
| 404 | پروژه پیدا نشد (یا بایگانی شده) |
| 400 | بدنه JSON نامعتبر یا بیش از ۱۰۰۰ آیتم |

> کلید را در برنامه عمومی نگذارید: [امنیت کلید API](kb:api-key-safety).
