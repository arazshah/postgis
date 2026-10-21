---
title: خطای SSL هنگام اتصال (server does not support SSL / certificate)؛ چه کنم؟
summary: حالت SSL ابزار را با حالت سرور هماهنگ کنید. معمولاً sslmode=require درست است؛ اگر ابزار قدیمی است و SSL ندارد، آن را به‌روز کنید. خاموش کردن SSL فقط برای آزمایش و با آگاهی از خطر است.
kind: trouble
keywords: ssl, sslmode, server does not support ssl, certificate verify failed, require, verify-full, خطای ssl, tls
related: ssl-modes, is-connection-secure, connection-string-formats
order: 30
reviewed: 2026-10-21
---
1. **`sslmode=require`** را در رشته اتصال یا تنظیمات ابزار بگذارید ([قالب‌ها](kb:connection-string-formats)).
2. `certificate verify failed`: با `verify-full` گواهی باید معتبر و نام میزبان درست باشد؛ ابتدا با `require` تست کنید و تفاوت‌ها را در [حالت‌های SSL](kb:ssl-modes) ببینید.
3. ابزار یا درایور بسیار قدیمی؟ نسخه را به‌روز کنید.
4. اتصال بدون رمزنگاری رمز و داده شما را در شبکه قابل‌دیدن می‌کند؛ [چرا SSL مهم است](kb:is-connection-secure).
