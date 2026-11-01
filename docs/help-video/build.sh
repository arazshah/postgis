#!/usr/bin/env bash
# ساخت ویدیوی یک راهنما: build.sh <slug>   (سناریو: scenarios/<slug>.js؛ متن کارت‌ها از core/help.py)
# خروجی: static/help/video/<slug>.mp4 (۱۹۲۰×۱۰۸۰، H.264 + AAC) و <slug>.jpg (پوستر ۱۲۸۰×۷۲۰)
set -euo pipefail
slug=$1
here=$(cd "$(dirname "$0")" && pwd); root=$(cd "$here/../.." && pwd)
work=${WORK:-/tmp/help-video-$slug}; rm -rf "$work"; mkdir -p "$work"
export DJANGO_TESTING=1 DJANGO_DEBUG=1 DATABASE_URL="sqlite:///$work/demo.sqlite3" MEDIA_ROOT="$work/media"
export NODE_PATH=${NODE_PATH:-$(npm root -g)}
cd "$root"
export GUIDE_JSON=$(python - "$slug" <<'PY'
import json, os, sys
sys.path.insert(0, ".")
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
import django; django.setup()
from core.help import GUIDES
if sys.argv[1] == "intro":
    print(json.dumps({"title": "معرفی ژئوپایگاه در یک و نیم دقیقه", "badge": "معرفی سرویس", "next": GUIDES[0].title,
                      "summary": "پایگاه داده مکانی PostGIS آنلاین: ساخت، اتصال QGIS، ورود فایل، SQL مکانی، نقشه قابل اشتراک و WMS/WFS.",
                      "steps": ["ساخت پایگاه", "ورود داده", "SQL مکانی", "نقشه", "انتشار"]}, ensure_ascii=False)); raise SystemExit
i = next(k for k, g in enumerate(GUIDES) if g.slug == sys.argv[1])
g = GUIDES[i]
print(json.dumps({"title": g.title, "summary": g.summary, "no": i + 1, "of": len(GUIDES),
                  "steps": [s[0] for s in g.steps], "next": GUIDES[i + 1].title if i + 1 < len(GUIDES) else ""}, ensure_ascii=False))
PY
)
profile=$(node -e "console.log(require('./docs/help-video/scenarios/$slug.js').profile)")
export PORT=${PORT:-8765}
clean_pg() {  # پایگاه‌ها و نقش‌های نمایشی سرور محلی
  for d in $(PGPASSWORD=postgres psql -h localhost -p ${PG_PORT:-5432} -U postgres -Atc "select datname from pg_database where datname like 'gp\_%'" 2>/dev/null); do
    PGPASSWORD=postgres psql -h localhost -p ${PG_PORT:-5432} -U postgres -qc "drop database \"$d\" with (force)" 2>/dev/null || true; done
  for r in $(PGPASSWORD=postgres psql -h localhost -p ${PG_PORT:-5432} -U postgres -Atc "select rolname from pg_roles where rolname like 'gp\_%'" 2>/dev/null); do
    PGPASSWORD=postgres psql -h localhost -p ${PG_PORT:-5432} -U postgres -qc "drop role \"$r\"" 2>/dev/null || true; done
}
if [ "$profile" = main ] || [ "${REAL_PG:-}" = 1 ]; then export REAL_PG=1; clean_pg; fi
python docs/help-video/demo.py init "$profile"
python docs/help-video/demo.py serve >"$work/server.log" 2>&1 &
srv=$!; wk=""
if [ -n "${REAL_PG:-}" ]; then python manage.py run_worker >"$work/worker.log" 2>&1 & wk=$!; fi
trap 'kill $srv $wk 2>/dev/null || true; [ -z "${REAL_PG:-}" ] || clean_pg' EXIT
for _ in $(seq 60); do curl -sf -o /dev/null localhost:$PORT/class/ && break; sleep 0.5; done
node docs/help-video/record.js "$slug" "$work/rec" | tee "$work/rec.log"
webm=$(sed -n 's/^VIDEO //p' "$work/rec.log")
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$webm")
python docs/help-video/music.py "$work/music.wav" "$dur"
ffmpeg -v error -y -ss 0.6 -i "$webm" -i "$work/music.wav" \
  -vf "fps=30,scale=1920:1080:flags=lanczos,format=yuv420p" -c:v libx264 -preset medium -crf 20 \
  -c:a aac -b:a 128k -shortest -movflags +faststart "static/help/video/$slug.mp4"
ffmpeg -v error -y -ss 2.5 -i "static/help/video/$slug.mp4" -frames:v 1 -vf scale=1280:720 -q:v 3 "static/help/video/$slug.jpg"
ffprobe -v error -show_entries format=duration -of csv=p=0 "static/help/video/$slug.mp4"
