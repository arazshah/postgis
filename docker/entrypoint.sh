#!/bin/sh
set -e

# volumeهای قدیمی ممکن است مالکشان root باشد (Permission denied در بکاپ و داده OSM)؛
# اگر به‌عنوان root شروع شده‌ایم، مالکیت را درست می‌کنیم و بعد با کاربر app دوباره اجرا می‌شویم.
if [ "$(id -u)" = "0" ]; then
  for d in /app/media /app/backups /app/ows /app/osm /app/rasters /app/pylibs; do
    mkdir -p "$d"
    chown -R app:app "$d" 2>/dev/null || true
  done
  exec setpriv --reuid=app --regid=app --init-groups "$0" "$@"
fi

# به‌روزرسانی خودکار smart-spatial-system در هر بار شروع کانتینر (بدون نیاز به بیلد/دیپلوی تازه).
# نسخه جدید در volume ماندگار /app/pylibs نصب می‌شود و روی نسخه داخل ایمیج اولویت دارد.
# خطا (مثلاً قطع PyPI) کشنده نیست و با همان نسخه قبلی ادامه می‌دهیم. غیرفعال‌سازی: AUTO_UPDATE_SSS=0
if [ "${AUTO_UPDATE_SSS:-1}" = "1" ]; then
  timeout 120 pip install --user --upgrade --quiet --disable-pip-version-check smart-spatial-system \
    || echo "به‌روزرسانی smart-spatial-system ناموفق بود؛ با نسخه فعلی ادامه می‌دهیم"
fi

# مایگریشن خودکار در هر دیپلوی (قابل غیرفعال‌سازی)
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi

# بعد از تعویض ایمیج panel-db از alpine (musl) به pgvector (Debian/glibc) ترتیب مرتب‌سازی متن‌ها عوض می‌شود و
# نمایه‌های متنی باید یک بار بازسازی شوند. نشانه در volume ماندگار است تا فقط یک بار اجرا شود.
if [ "${RUN_MIGRATIONS:-1}" = "1" ] && [ ! -f /app/media/.panel-reindexed-glibc ]; then
  if python manage.py reindex_panel; then
    touch /app/media/.panel-reindexed-glibc
  else
    echo "reindex_panel ناموفق بود؛ در دیپلوی بعدی دوباره تلاش می‌شود"
  fi
fi

# مقاله‌های پایگاه دانش از kb/content (مقاله‌های ویرایش‌شده در پنل دست‌نخورده می‌مانند)
if [ "${RUN_MIGRATIONS:-1}" = "1" ] && [ "${KB_SYNC:-1}" = "1" ]; then
  python manage.py kb_sync || echo "kb_sync ناموفق بود؛ ادامه راه‌اندازی"
fi

# embedding مقاله‌ها برای دستیار هوشمند (فقط اگر تنظیم شده باشد؛ تکه‌های تغییرنکرده دوباره ساخته نمی‌شوند)
if [ "${RUN_MIGRATIONS:-1}" = "1" ] && [ "${KB_SYNC:-1}" = "1" ]; then
  timeout 120 python manage.py kb_embed || echo "kb_embed ناموفق بود؛ run_maintenance دوباره تلاش می‌کند"
fi

# ساخت ادمین اولیه در اولین اجرا (اختیاری)
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  python manage.py ensure_superuser || true
fi

exec "$@"
