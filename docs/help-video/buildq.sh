#!/usr/bin/env bash
# ساخت پشت‌سرهم چند ویدیو: buildq.sh slug1 slug2 ...  (گزارش هر کدام در /tmp/vq-<slug>.log)
cd "$(dirname "$0")/../.."
for s in "$@"; do
  if docs/help-video/build.sh "$s" >"/tmp/vq-$s.log" 2>&1; then echo "OK $s $(tail -1 /tmp/vq-$s.log)"; else echo "FAIL $s"; fi
done
