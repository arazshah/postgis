---
title: خطای «connection refused» یا «timeout» هنگام اتصال؛ چه کنم؟
summary: بیشتر وقت‌ها میزبان یا پورت اشتباه است، پایگاه داده منقضی یا غیرفعال شده، یا شبکه شما (فایروال، VPN) پورت را می‌بندد. اطلاعات اتصال را دوباره از داشبورد بردارید و وضعیت پایگاه داده را بررسی کنید.
kind: trouble
keywords: connection refused, timeout, could not connect, اتصال برقرار نشد, پورت بسته, فایروال, vpn, could not translate host name, no route to host
related: connection-info, expiry-lifecycle, err-ssl-off, err-password-auth, support-ticket
featured: yes
order: 10
reviewed: 2026-10-21
---
## بررسی به ترتیب

1. **اطلاعات اتصال:** میزبان و پورت را مستقیم از [اطلاعات اتصال](kb:connection-info) کپی کنید؛ پورت پیش‌فرض ۵۴۳۲ نیست و نباید حدس زده شود.
2. **وضعیت پایگاه داده:** اگر [اعتبار تمام شده](kb:expiry-lifecycle) ورود غیرفعال است.
3. **شبکه شما:** از شبکه دیگر (مثلاً هات‌اسپات موبایل) امتحان کنید. فایروال سازمانی یا VPN ممکن است پورت‌های غیرمعمول را ببندند.
4. **نام میزبان:** `could not translate host name` یعنی نام اشتباه یا DNS شما مشکل دارد.
5. **تعداد اتصال:** ممکن است به [سقف اتصال](kb:err-too-many-connections) رسیده باشید.
6. **SSL:** اگر پیام درباره SSL است، [این راهنما](kb:err-ssl-off).

اگر هنوز مشکل دارید، در [تیکت](kb:support-ticket) نام پایگاه داده و متن دقیق خطا را بنویسید (**رمز را ننویسید**).
