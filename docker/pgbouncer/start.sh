#!/bin/sh
# ساخت پیکربندی PgBouncer از متغیرهای محیطی و اجرای آن
set -eu
if [ -z "${DB_HOST:-}" ] || [ -z "${AUTH_PASSWORD:-}" ]; then
  # تا تنظیم نشده، سرویس بیکار می‌ماند (و سالم گزارش می‌شود) تا استقرار Coolify شکست نخورد
  echo "PgBouncer غیرفعال است: PGBOUNCER_DB_HOST و PGBOUNCER_AUTH_PASSWORD را تنظیم کنید."
  touch /tmp/pgbouncer.disabled
  exec sleep infinity
fi
export DB_PORT="${DB_PORT:-5432}" AUTH_USER="${AUTH_USER:-gp_pgbouncer}" AUTH_DBNAME="${AUTH_DBNAME:-postgres}"
export MAX_CLIENT_CONN="${MAX_CLIENT_CONN:-2000}" DEFAULT_POOL_SIZE="${DEFAULT_POOL_SIZE:-5}"
export MAX_DB_CONNECTIONS="${MAX_DB_CONNECTIONS:-15}" SERVER_TLS_SSLMODE="${SERVER_TLS_SSLMODE:-prefer}"
export CLIENT_TLS_SSLMODE="${CLIENT_TLS_SSLMODE:-allow}"
export CONF_DIR="${CONF_DIR:-/etc/pgbouncer}"
mkdir -p "$CONF_DIR"
if [ ! -f "$CONF_DIR/server.crt" ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=${PUBLIC_HOST:-pgbouncer}" \
    -keyout "$CONF_DIR/server.key" -out "$CONF_DIR/server.crt" 2>/dev/null
  chmod 600 "$CONF_DIR/server.key"
fi
printf '"%s" "%s"\n' "$AUTH_USER" "$AUTH_PASSWORD" > "$CONF_DIR/userlist.txt"
chmod 600 "$CONF_DIR/userlist.txt"
envsubst '${DB_HOST} ${DB_PORT} ${AUTH_USER} ${AUTH_DBNAME} ${MAX_CLIENT_CONN} ${DEFAULT_POOL_SIZE} ${MAX_DB_CONNECTIONS} ${SERVER_TLS_SSLMODE} ${CLIENT_TLS_SSLMODE} ${CONF_DIR}' \
  < "${TEMPLATE:-/pgbouncer.ini.tmpl}" > "$CONF_DIR/pgbouncer.ini"
exec pgbouncer "$CONF_DIR/pgbouncer.ini"
