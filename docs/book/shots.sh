#!/usr/bin/env bash
# تصویرهای کتاب از رابط واقعی روی داده‌ی نمایشی (همان محیط docs/help-video)
#   docs/book/shots.sh            همه‌ی تصویرها
#   docs/book/shots.sh explore    فقط تصویرهایی که نامشان این را دارد
# پیش‌نیاز: PostgreSQL+PostGIS روی localhost:5432 (کاربر postgres/postgres)، gdal-bin، Playwright
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); root=$(cd "$here/../.." && pwd)
work=${WORK:-/tmp/book-demo}
export DJANGO_TESTING=1 DJANGO_DEBUG=1 DATABASE_URL="sqlite:///$work/demo.sqlite3" MEDIA_ROOT="$work/media" REAL_PG=1
export NODE_PATH=${NODE_PATH:-$(npm root -g)} PORT=${PORT:-8765}
cd "$root"
if [ ! -f "$work/demo.sqlite3" ] || [ -n "${FRESH:-}" ]; then
  rm -rf "$work"; mkdir -p "$work"
  for d in $(PGPASSWORD=postgres psql -h localhost -U postgres -Atc "select datname from pg_database where datname like 'gp\_%'"); do
    PGPASSWORD=postgres psql -h localhost -U postgres -qc "drop database \"$d\" with (force)"; done
  for r in $(PGPASSWORD=postgres psql -h localhost -U postgres -Atc "select rolname from pg_roles where rolname like 'gp\_%'"); do
    PGPASSWORD=postgres psql -h localhost -U postgres -qc "drop role \"$r\""; done
  python docs/help-video/demo.py init main
  python docs/book/shots_setup.py
fi
python docs/help-video/demo.py serve >"$work/server.log" 2>&1 & srv=$!
python manage.py run_worker >"$work/worker.log" 2>&1 & wk=$!
trap 'kill $srv $wk 2>/dev/null || true' EXIT
for _ in $(seq 60); do curl -sf -o /dev/null "localhost:$PORT/" && break; sleep 0.5; done
node "$here/shots.js" "${1:-}"
