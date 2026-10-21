---
title: چطور از REST API ردیف اضافه یا ویرایش کنم؟
summary: فقط کلیدی که مجوز «نوشتن» دارد می‌تواند ردیف بسازد، ویرایش یا حذف کند. جدول باید در REST فعال و نوشتن برای آن مجاز باشد. کلید نوشتن را فقط در سرور خودتان نگه دارید.
kind: howto
keywords: rest نوشتن, post, put, patch, delete, ثبت داده, can_write, کلید نوشتن, ویرایش از api, crud
related: rest-api-overview, api-keys, api-key-safety, field-form
order: 120
reviewed: 2026-10-21
---
1. در صفحه انتشار کلیدی با گزینه **اجازه نوشتن (REST API)** بسازید ([کلیدها](kb:api-keys)).
2. جدول را در صفحه REST فعال کنید.
3. درخواست JSON بفرستید:

```bash
curl -X POST https://سایت-شما/rest/demo/places/ \
  -H "Authorization: Bearer gpk_..." -H "Content-Type: application/json" \
  -d '{"name": "نمونه"}'
```

برای ویرایش و حذف از آدرس یک ردیف (`/rest/demo/places/<کلید>/`) استفاده کنید.

!!! warning
    کلید نوشتن در مرورگر کاربر **نباید** باشد ([امنیت](kb:api-key-safety)). برای جمع‌آوری داده از مردم از [فرم میدانی](kb:field-form) استفاده کنید.
