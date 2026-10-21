---
title: خطای «password authentication failed»؛ رمز یا نام کاربری اشتباه است؟
summary: رمز یا نام کاربری با آنچه روی سرور ثبت شده یکی نیست. نام کاربری را از اطلاعات اتصال کپی کنید، کاراکترهای ویژه رمز را در رشته اتصال URL-encode کنید و اگر رمز را گم کرده‌اید رمز جدید بگیرید.
kind: trouble
keywords: password authentication failed, احراز هویت, رمز اشتباه, fatal 28p01, نام کاربری, url encode, کاراکتر ویژه رمز, @ در رمز
related: reset-db-password, connection-info, connection-string-formats, password-rules
featured: yes
order: 20
reviewed: 2026-10-21
---
## علت‌های رایج

| علت | راه‌حل |
|---|---|
| رمز تغییر کرده یا گم شده | [رمز جدید](kb:reset-db-password) |
| نام کاربری حدسی | نام را از [اطلاعات اتصال](kb:connection-info) کپی کنید |
| رمز در رشته URL است و کاراکتر ویژه دارد (`@ : / # %`) | URL-encode کنید ([قالب‌ها](kb:connection-string-formats)) |
| کاربر دیگری (مثلاً کاربر اضافه) با رمز اصلی | هر کاربر رمز خودش را دارد ([کاربران](kb:database-users)) |
| فاصله یا کاراکتر نامرئی هنگام کپی | رمز را دوباره بدون فاصله بچسبانید |
| پایگاه داده منقضی | [چرخه اعتبار](kb:expiry-lifecycle) |

بعد از تغییر رمز، برنامه‌ها و QGIS را هم به‌روز کنید. [قواعد رمز](kb:password-rules).
