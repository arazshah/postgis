---
title: کلید API چیست و چطور بسازم و بفرستم؟
summary: کلید API با gpk_ شروع می‌شود و دسترسی به لایه‌های خصوصی را می‌دهد. در صفحه انتشار بسازید (فقط یک بار کامل دیده می‌شود) و با Authorization: Bearer، Basic، هدر X-API-Key یا پارامتر ?key= بفرستید.
kind: howto
keywords: کلید api, gpk, bearer, x-api-key, authorization, توکن, ساخت کلید, باطل کردن کلید, پارامتر key
related: api-key-safety, layer-privacy, rest-api-overview, rest-write-access
featured: yes
order: 60
reviewed: 2026-10-21
---
## ساخت

صفحه **انتشار ← کلیدها ← ساخت کلید** (نام دلخواه بدهید). متن کامل کلید **فقط همان لحظه** نمایش داده می‌شود؛ ذخیره کنید.

## ارسال

| روش | مثال |
|---|---|
| هدر Bearer | `Authorization: Bearer gpk_...` |
| هدر X-API-Key | `X-API-Key: gpk_...` |
| پارامتر آدرس | `...?key=gpk_...` |
| Basic (برای WMS/WFS) | رمز = کلید |

## مدیریت

- هر کلید را جداگانه **باطل** کنید؛ برنامه‌هایی که از آن استفاده می‌کنند از کار می‌افتند.
- کلید به‌طور پیش‌فرض فقط‌خواندنی است؛ مجوز نوشتن جداست ([REST](kb:rest-write-access)).
- زمان آخرین استفاده هر کلید نمایش داده می‌شود.

نکات ایمنی: [کلید در مرورگر](kb:api-key-safety).
