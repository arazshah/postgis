#!/usr/bin/env bash
# ساخت یک ویدیوی راهنما: build.sh teacher|student slug
# خروجی: static/help/video/<slug>.mp4 و <slug>.jpg (۱۹۲۰×۱۰۸۰، H.264 + AAC، پوستر ۱۲۸۰×۷۲۰)
set -euo pipefail
role=$1; slug=$2
here=$(cd "$(dirname "$0")" && pwd); root=$(cd "$here/../.." && pwd)
work=${WORK:-/tmp/help-video-$slug}; rm -rf "$work"; mkdir -p "$work"
export DJANGO_TESTING=1 DJANGO_DEBUG=1 DATABASE_URL="sqlite:///$work/demo.sqlite3"
cd "$root"
python docs/help-video/demo.py init "$role"
python docs/help-video/demo.py serve >"$work/server.log" 2>&1 &
srv=$!; trap 'kill $srv 2>/dev/null || true' EXIT
for _ in $(seq 40); do curl -sf -o /dev/null localhost:8765/class/ && break; sleep 0.5; done
node docs/help-video/record.js "$role" "$work/rec" | tee "$work/rec.log"
webm=$(sed -n 's/^VIDEO //p' "$work/rec.log")
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$webm")
python docs/help-video/music.py "$work/music.wav" "$dur"
ffmpeg -v error -y -ss 0.6 -i "$webm" -i "$work/music.wav" \
  -vf "fps=30,scale=1920:1080:flags=lanczos,format=yuv420p" -c:v libx264 -preset medium -crf 21 \
  -c:a aac -b:a 128k -shortest -movflags +faststart "static/help/video/$slug.mp4"
ffmpeg -v error -y -ss 2.5 -i "static/help/video/$slug.mp4" -frames:v 1 -vf scale=1280:720 -q:v 3 "static/help/video/$slug.jpg"
ffprobe -v error -show_entries format=duration -of csv=p=0 "static/help/video/$slug.mp4"
