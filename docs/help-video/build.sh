#!/usr/bin/env bash
# ساخت ویدیوی یک راهنما: build.sh <slug>   (سناریو: scenarios/<slug>.js؛ متن کارت‌ها از core/help.py)
# خروجی: static/help/video/<slug>.mp4 (۱۹۲۰×۱۰۸۰، H.264 + AAC) و <slug>.jpg (پوستر ۱۲۸۰×۷۲۰)
set -euo pipefail
slug=$1
here=$(cd "$(dirname "$0")" && pwd); root=$(cd "$here/../.." && pwd)
work=${WORK:-/tmp/help-video-$slug}; rm -rf "$work"; mkdir -p "$work"
export DJANGO_TESTING=1 DJANGO_DEBUG=1 DATABASE_URL="sqlite:///$work/demo.sqlite3"
export NODE_PATH=${NODE_PATH:-$(npm root -g)}
cd "$root"
export GUIDE_JSON=$(python - "$slug" <<'PY'
import json, os, sys
sys.path.insert(0, ".")
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
import django; django.setup()
from core.help import GUIDES
i = next(k for k, g in enumerate(GUIDES) if g.slug == sys.argv[1])
g = GUIDES[i]
print(json.dumps({"title": g.title, "summary": g.summary, "no": i + 1, "of": len(GUIDES),
                  "steps": [s[0] for s in g.steps], "next": GUIDES[i + 1].title if i + 1 < len(GUIDES) else ""}, ensure_ascii=False))
PY
)
profile=$(node -e "console.log(require('./docs/help-video/scenarios/$slug.js').profile)")
python docs/help-video/demo.py init "$profile"
python docs/help-video/demo.py serve >"$work/server.log" 2>&1 &
srv=$!; trap 'kill $srv 2>/dev/null || true' EXIT
for _ in $(seq 60); do curl -sf -o /dev/null localhost:8765/class/ && break; sleep 0.5; done
node docs/help-video/record.js "$slug" "$work/rec" | tee "$work/rec.log"
webm=$(sed -n 's/^VIDEO //p' "$work/rec.log")
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$webm")
python docs/help-video/music.py "$work/music.wav" "$dur"
ffmpeg -v error -y -ss 0.6 -i "$webm" -i "$work/music.wav" \
  -vf "fps=30,scale=1920:1080:flags=lanczos,format=yuv420p" -c:v libx264 -preset medium -crf 20 \
  -c:a aac -b:a 128k -shortest -movflags +faststart "static/help/video/$slug.mp4"
ffmpeg -v error -y -ss 2.5 -i "static/help/video/$slug.mp4" -frames:v 1 -vf scale=1280:720 -q:v 3 "static/help/video/$slug.jpg"
ffprobe -v error -show_entries format=duration -of csv=p=0 "static/help/video/$slug.mp4"
