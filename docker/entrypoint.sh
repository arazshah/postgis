#!/bin/sh
set -e

# volumeهای قدیمی ممکن است مالکشان root باشد (Permission denied در بکاپ و داده OSM)؛
# اگر به‌عنوان root شروع شده‌ایم، مالکیت را درست می‌کنیم و بعد با کاربر app دوباره اجرا می‌شویم.
if [ "$(id -u)" = "0" ]; then
  for d in /app/media /app/backups /app/ows /app/osm /app/rasters; do
    mkdir -p "$d"
    chown -R app:app "$d" 2>/dev/null || true
  done
  exec setpriv --reuid=app --regid=app --init-groups "$0" "$@"
fi

# مایگریشن خودکار در هر دیپلوی (قابل غیرفعال‌سازی)
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi

# مقاله‌های پایگاه دانش از kb/content (مقاله‌های ویرایش‌شده در پنل دست‌نخورده می‌مانند)
if [ "${RUN_MIGRATIONS:-1}" = "1" ] && [ "${KB_SYNC:-1}" = "1" ]; then
  python manage.py kb_sync || echo "kb_sync ناموفق بود؛ ادامه راه‌اندازی"
fi

# ساخت ادمین اولیه در اولین اجرا (اختیاری)
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  python manage.py ensure_superuser || true
fi

exec "$@"
