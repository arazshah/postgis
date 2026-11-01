#!/usr/bin/env bash
# فشرده‌سازی ویدیوها برای مخزن (حدود نصف حجم، با همان خوانایی): compress.sh [slug...]  (بدون ورودی: همه)
cd "$(dirname "$0")/../../static/help/video"
files=("$@"); [ ${#files[@]} -gt 0 ] || files=($(ls *.mp4 | sed 's/\.mp4$//'))
printf '%s\n' "${files[@]}" | xargs -P 3 -I{} sh -c 'ffmpeg -v error -y -i {}.mp4 -c:v libx264 -preset medium -crf 27 -c:a copy -movflags +faststart {}.tmp.mp4 && mv {}.tmp.mp4 {}.mp4 && echo done {}'
