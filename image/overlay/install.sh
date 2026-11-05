#!/usr/bin/env bash
# نصب pgpro داخل ریشه‌ی ایمیج (chroot) یا یک ماشین Debian/Ubuntu آزمایشی. همه‌چیز اینجا آماده می‌شود
# تا دستگاه در اولین روشن شدن هیچ دانلودی نکند.
#
# ورودی (متغیر محیطی):
#   PGPRO_SRC          پوشه‌ی کد برنامه (پیش‌فرض: دو سطح بالاتر از همین فایل)
#   PGPRO_VERSION      شماره‌ی نسخه (پیش‌فرض: 0.1.0)
#   PGPRO_SKIP_PACKAGES=1  رد کردن apt (بسته‌ها از قبل نصب‌اند)
#   PGPRO_SKIP_SYSTEMD=1   رد کردن enable سرویس‌ها (محیط بدون systemd)
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${PGPRO_SRC:-$(cd "$HERE/../.." && pwd)}
VERSION=${PGPRO_VERSION:-0.1.0}
OPT=/opt/pgpro
REL=$OPT/releases/$VERSION
export DEBIAN_FRONTEND=noninteractive

step() { printf '\n== %s\n' "$*"; }

# ── ۱) بسته‌های سیستم ──────────────────────────────────────────────────────────────
if [ "${PGPRO_SKIP_PACKAGES:-0}" != 1 ]; then
  step "بسته‌های سیستم"
  # جلوگیری از بالا آمدن سرویس‌ها داخل chroot
  printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d; chmod +x /usr/sbin/policy-rc.d
  apt-get update
  PGV=$(apt-cache depends postgresql | sed -n 's/^ *Depends: postgresql-\([0-9][0-9]*\)$/\1/p' | sort -n | tail -1)
  [ -n "$PGV" ] || { echo "نسخه‌ی PostgreSQL پیدا نشد."; exit 1; }
  apt-get install -y --no-install-recommends \
    "postgresql-$PGV" "postgresql-$PGV-postgis-3" "postgresql-$PGV-pgrouting" "postgresql-$PGV-pgvector" \
    postgresql-client-common gdal-bin nginx avahi-daemon libnss-mdns \
    python3 python3-venv ca-certificates curl openssl sudo rsync cron fake-hwclock util-linux openssh-server
  rm -f /usr/sbin/policy-rc.d
fi

# ── ۲) کاربرها ────────────────────────────────────────────────────────────────────
step "کاربرها"
id pgpro >/dev/null 2>&1 || useradd --system --home-dir /var/lib/pgpro --shell /usr/sbin/nologin pgpro
id support >/dev/null 2>&1 || useradd --create-home --shell /bin/bash support
usermod -p '*' support      # بدون رمز؛ فقط کلید SSH
usermod -p '*' root         # ورود root با رمز بسته (Armbian رمز پیش‌فرض 1234 دارد)
rm -f /root/.not_logged_in_yet   # ویزارد اولین ورود Armbian

# ── ۳) برنامه ─────────────────────────────────────────────────────────────────────
step "کد برنامه ← $REL"
install -d "$OPT/releases"
rm -rf "$REL"
rsync -a --delete \
  --exclude '.git' --exclude '.github' --exclude 'image' --exclude 'docs' --exclude 'tests' \
  --exclude '__pycache__' --exclude '*.sqlite3' --exclude 'staticfiles' --exclude '.ruff_cache' \
  "$SRC"/ "$REL"/
ln -sfn "$REL" "$OPT/current"

step "محیط پایتون"
[ -d "$OPT/venv" ] || python3 -m venv "$OPT/venv"
"$OPT/venv/bin/pip" install --no-cache-dir --disable-pip-version-check --prefer-binary -r "$REL/requirements.txt"

step "فایل‌های استاتیک و بایت‌کد"
( cd "$REL" && DJANGO_SETTINGS_MODULE=config.settings_device DJANGO_SECRET_KEY=build-only \
    "$OPT/venv/bin/python" manage.py collectstatic --noinput -v0 )
"$OPT/venv/bin/python" -m compileall -q "$REL" "$OPT/venv/lib" >/dev/null 2>&1 || true
chown -R root:root "$OPT"; chmod -R a+rX "$OPT"

# ── ۴) فایل‌های سیستم ─────────────────────────────────────────────────────────────
step "فایل‌های سیستم"
rsync -a "$HERE/rootfs/" /
chmod 755 /usr/local/sbin/pgpro-*
chmod 440 /etc/sudoers.d/pgpro
printf 'PGPRO_VERSION=%s\n' "$VERSION" > /etc/pgpro/version.env
[ -f /etc/pgpro/support_keys ] || install -m 644 /dev/null /etc/pgpro/support_keys
install -d -m 755 /etc/pgpro/support_keys.d
echo pgpro > /etc/hostname
if grep -q '^127.0.1.1' /etc/hosts; then sed -i 's/^127.0.1.1.*/127.0.1.1 pgpro/' /etc/hosts; else echo '127.0.1.1 pgpro' >> /etc/hosts; fi
ln -sf /usr/share/zoneinfo/Asia/Tehran /etc/localtime
echo Asia/Tehran > /etc/timezone
ln -sf /etc/nginx/sites-available/pgpro /etc/nginx/sites-enabled/pgpro
rm -f /etc/nginx/sites-enabled/default

# خوشه‌ی پیش‌فرضی که بسته ساخته حذف می‌شود؛ در اولین بوت خوشه‌ی تازه با رمز یکتا ساخته می‌شود
for d in /usr/lib/postgresql/*/; do v=$(basename "$d"); pg_dropcluster --stop "$v" main 2>/dev/null || true; done

if [ "${PGPRO_SKIP_SYSTEMD:-0}" != 1 ]; then
  step "فعال‌سازی سرویس‌ها"
  # سرویس‌های خودمان و اصلی باید فعال شوند (خطا = توقف)؛ fake-hwclock در Debian ممکن است mask باشد
  systemctl enable pgpro-sshkeys.service pgpro-firstboot.service pgpro-web.service pgpro-worker.service \
    nginx.service avahi-daemon.service ssh.service cron.service postgresql.service
  # برد باتری ساعت ندارد؛ fake-hwclock آخرین زمان را نگه می‌دارد (اگر نشد، فقط هشدار)
  systemctl unmask fake-hwclock.service 2>/dev/null || true
  systemctl enable fake-hwclock.service || echo "هشدار: fake-hwclock فعال نشد."
fi

# ── ۵) پاک‌سازی برای ایمیج ─────────────────────────────────────────────────────────
step "پاک‌سازی"
apt-get clean 2>/dev/null || true
rm -rf /var/lib/apt/lists/* /root/.cache /tmp/pip-* 2>/dev/null || true
# کلیدهای میزبان و شناسه‌ی ماشین باید برای هر دستگاه تازه ساخته شوند
rm -f /etc/ssh/ssh_host_*
: > /etc/machine-id
echo "نصب pgpro $VERSION کامل شد."
