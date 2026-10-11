#!/bin/sh
set -e

# مایگریشن خودکار در هر دیپلوی (قابل غیرفعال‌سازی)
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi

# ساخت ادمین اولیه در اولین اجرا (اختیاری)
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  python manage.py ensure_superuser || true
fi

exec "$@"
