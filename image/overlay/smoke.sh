#!/usr/bin/env bash
# آزمون دود داخل chroot ایمیج (بدون systemd): اولین بوت واقعی، ورود، ساخت پایگاه PostGIS، قاعده‌های pg_hba، بازنشانی کارخانه.
# هر چیزی که این آزمون می‌سازد در پایان پاک می‌شود تا ایمیج تمیز بماند.
set -euo pipefail

PGPRO_HOME=/opt/pgpro
HOST_H='Host: pgpro.local'
BASE=http://127.0.0.1:8000
fail() { echo "✗ $*" >&2; exit 1; }
ok() { echo "✓ $*"; }

cleanup() {
  pkill -f 'gunicorn config.wsgi' 2>/dev/null || true
  for d in /usr/lib/postgresql/*/; do pg_ctlcluster "$(basename "$d")" main stop -m fast 2>/dev/null || true; done
}
trap cleanup EXIT

# اجرای قبلی نیمه‌کاره مانده باشد، از حالت تمیز شروع می‌کنیم
[ -f /var/lib/pgpro/.firstboot-done ] && /usr/local/sbin/pgpro-factory-reset --yes

echo "== ۱) اولین بوت"
PGPRO_NO_START=1 /usr/local/sbin/pgpro-firstboot
[ -f /var/lib/pgpro/.firstboot-done ] || fail "نشانه‌ی firstboot ساخته نشد"
ok "firstboot کامل شد"
[ "$(stat -c %a /etc/pgpro/pgpro.env)" = 640 ] || fail "مجوز pgpro.env درست نیست"
grep -q '^DJANGO_SECRET_KEY=.\{40,\}' /etc/pgpro/pgpro.env || fail "کلید Django ساخته نشده"
ok "رمزهای یکتا ساخته شد"

echo "== ۲) برنامه (gunicorn)"
setpriv --reuid=pgpro --regid=pgpro --init-groups env -C "$PGPRO_HOME/current" \
  bash -c 'set -a; . /etc/pgpro/pgpro.env; . /etc/pgpro/version.env; set +a;
           exec "'"$PGPRO_HOME"'/venv/bin/gunicorn" config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --threads 2 --timeout 60' \
  >/tmp/gunicorn.log 2>&1 &
for _ in $(seq 1 60); do curl -fsS -H "$HOST_H" "$BASE/healthz" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS -H "$HOST_H" "$BASE/healthz" | grep -q '"ok"' || { cat /tmp/gunicorn.log; fail "healthz"; }
ok "healthz"
[ "$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: evil.example.com' "$BASE/accounts/login/")" = 400 ] || fail "Host بیگانه رد نشد"
ok "Host بیگانه رد می‌شود"

echo "== ۳) ورود و تغییر رمز"
jar=$(mktemp)
page=$(curl -sS -c "$jar" -b "$jar" -H "$HOST_H" "$BASE/accounts/login/")
echo "$page" | grep -q 'نام کاربری یا موبایل' || fail "صفحه‌ی ورود رمزی نیست"
tok=$(awk '$6=="csrftoken"{print $7}' "$jar")
resp=$(curl -sS -c "$jar" -b "$jar" -H "$HOST_H" -d "csrfmiddlewaretoken=$tok&identifier=admin&password=pgpro" \
  -o /dev/null -w '%{http_code} %{redirect_url}' "$BASE/accounts/login/")
case "$resp" in 302*) ;; *) fail "ورود admin/pgpro ناموفق: $resp" ;; esac
loc=$(curl -sS -c "$jar" -b "$jar" -H "$HOST_H" -o /dev/null -w '%{redirect_url}' "$BASE/dashboard/")
case "$loc" in *"/device/password/"*) ok "ورود با رمز پیش‌فرض و اجبار به تغییر رمز" ;; *) fail "اجبار تغییر رمز کار نکرد: $loc" ;; esac
tok=$(awk '$6=="csrftoken"{print $7}' "$jar")
curl -sS -c "$jar" -b "$jar" -H "$HOST_H" -d "csrfmiddlewaretoken=$tok&old=pgpro&new1=Smoke-Pass-91x&new2=Smoke-Pass-91x" \
  -o /dev/null "$BASE/device/password/"
code=$(curl -sS -c "$jar" -b "$jar" -H "$HOST_H" -o /dev/null -w '%{http_code}' "$BASE/dashboard/")
[ "$code" = 200 ] || fail "داشبورد بعد از تغییر رمز: $code"
ok "داشبورد باز شد"

echo "== ۴) ساخت پایگاه PostGIS"
/usr/local/sbin/pgpro-manage shell -c "
from accounts.models import User
from databases import services
u = User.objects.get(username='admin')
db = services.create_database(u, 'smoke', 'Smoke-Db-Pass-91', ['postgis', 'pgrouting'])
assert db.status == 'active', db.status
print('db', db.db_name, db.role_name, db.status)
from databases.models import DatabaseServer
s = DatabaseServer.objects.get(is_default=True)
assert s.last_check_ok, s.last_check_message
print('server ok', s.server_version, s.postgis_version, s.public_host)
"
ok "پایگاه ساخته شد و سرور سالم است"
PGPASSWORD='Smoke-Db-Pass-91' psql -h 127.0.0.1 -U gp_smoke_user -d gp_smoke -Atc "SELECT postgis_version()" | grep -q . || fail "اتصال کاربر به PostGIS"
ok "اتصال کاربر و PostGIS"
PGPASSWORD='Smoke-Db-Pass-91' psql -h 127.0.0.1 -U gp_smoke_user -d gp_smoke -Atc "SELECT 'x' FROM pg_extension WHERE extname='pgrouting'" | grep -q x || fail "pgrouting نصب نشد"
ok "pgRouting"

echo "== ۵) pg_hba: ادمین داخلی فقط از خود دستگاه"
bad=$(runuser -u postgres -- psql -X -Atc "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL")
[ "$bad" = 0 ] || fail "pg_hba.conf خطا دارد"
rej=$(runuser -u postgres -- psql -X -Atc "SELECT count(*) FROM pg_hba_file_rules WHERE auth_method='reject'")
[ "$rej" -ge 4 ] || fail "قاعده‌های reject برای نقش‌های داخلی نیست"
ok "pg_hba.conf سالم است و نقش‌های داخلی از شبکه رد می‌شوند"
lan_ip=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' | head -1 || true)
if [ -n "$lan_ip" ]; then
  if PGPASSWORD="$(grep '^PGPRO_PG_ADMIN_PASSWORD=' /etc/pgpro/pgpro.env | cut -d= -f2-)" PGCONNECT_TIMEOUT=5 \
      psql -h "$lan_ip" -U pgpro_admin -d postgres -Atc 'select 1' >/dev/null 2>&1; then
    fail "pgpro_admin از آدرس شبکه وصل شد"
  fi
  ok "pgpro_admin از آدرس شبکه ($lan_ip) رد شد"
  PGPASSWORD='Smoke-Db-Pass-91' PGCONNECT_TIMEOUT=5 psql -h "$lan_ip" -U gp_smoke_user -d gp_smoke -Atc 'select 1' >/dev/null \
    || fail "کاربر عادی از آدرس شبکه وصل نشد"
  ok "کاربر عادی از آدرس شبکه وصل شد"
else
  echo "(آدرس خصوصی پیدا نشد؛ آزمون شبکه رد شد)"
fi

echo "== ۶) nginx"
# فقط نحو بررسی می‌شود؛ نبودن IPv6 در هسته‌ی محیط آزمون خطای socket می‌دهد که به نحو ربطی ندارد
nginx_out=$(nginx -t 2>&1 || true)
echo "$nginx_out" | grep -q 'syntax is ok' || { echo "$nginx_out"; fail "تنظیم nginx"; }
ok "نحو تنظیم nginx سالم است"

echo "== ۷) بازنشانی کارخانه"
cleanup
sleep 1
/usr/local/sbin/pgpro-factory-reset --yes
if [ -f /etc/pgpro/pgpro.env ] || [ -f /var/lib/pgpro/.firstboot-done ]; then fail "بازنشانی کامل نبود"; fi
ok "ایمیج دوباره تمیز است"
echo "همه‌ی آزمون‌های دود گذشت."
