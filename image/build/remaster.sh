#!/usr/bin/env bash
# ساخت ایمیج pgpro: ایمیج رسمی Armbian (Debian minimal) را برای NanoPi NEO3 می‌گیرد، داخل آن (chroot) همه‌چیز را
# نصب می‌کند (image/overlay/install.sh)، آزمون دود می‌زند، تمیز و کوچک می‌کند و خروجی .img.xz می‌دهد.
#
# اجرا (روی هاست arm64 با root؛ در GitHub Actions: ubuntu-24.04-arm):
#   sudo PGPRO_VERSION=0.1.0 bash image/build/remaster.sh [پوشه‌ی خروجی]
#
# متغیرها:
#   PGPRO_VERSION          (الزامی) نسخه‌ی خروجی
#   PGPRO_BASE_IMAGE       مسیر یا آدرس ایمیج پایه (.img یا .img.xz)؛ پیش‌فرض: آخرین Armbian Trixie minimal برای NEO3
#   PGPRO_EXTRA_GB         فضای افزوده برای نصب (پیش‌فرض ۳)
#   PGPRO_SKIP_SMOKE=1     رد کردن آزمون دود
#   PGPRO_SUPPORT_KEYS     مسیر فایل کلیدهای عمومی SSH پشتیبان (پیش‌فرض: image/support_keys.pub)
set -euo pipefail
export LC_ALL=C   # خروجی ابزارها (parted, dumpe2fs) انگلیسی و قابل‌تجزیه باشد

REPO=$(cd "$(dirname "$0")/../.." && pwd)
OUT=$(realpath -m "${1:-$PWD/pgpro-out}")
VERSION=${PGPRO_VERSION:?PGPRO_VERSION را بگذارید}
BASE=${PGPRO_BASE_IMAGE:-https://dl.armbian.com/nanopineo3/Trixie_current_minimal}
EXTRA_GB=${PGPRO_EXTRA_GB:-3}
KEYS=${PGPRO_SUPPORT_KEYS:-$REPO/image/support_keys.pub}
WORK=${PGPRO_WORK:-$(mktemp -d /var/tmp/pgpro-build.XXXXXX)}
ROOT=$WORK/root
NAME=pgpro-$VERSION-nanopineo3

[ "$(id -u)" = 0 ] || { echo "با root اجرا کنید." >&2; exit 1; }
[ "$(uname -m)" = aarch64 ] || echo "هشدار: هاست aarch64 نیست؛ chroot بدون qemu-user-static کار نمی‌کند." >&2
mkdir -p "$OUT" "$ROOT"
LOOP=""

unmount_all() {
  for m in dev/pts dev proc sys run; do umount -lf "$ROOT/$m" 2>/dev/null || true; done
  umount -lf "$ROOT" 2>/dev/null || true
  if [ -n "$LOOP" ]; then losetup -d "$LOOP" 2>/dev/null || true; fi
}
trap unmount_all EXIT

log() { printf '\n== %s\n' "$*"; }

# ── ۱) ایمیج پایه ───────────────────────────────────────────────────────────────────
log "ایمیج پایه"
IMG=$WORK/base.img
case "$BASE" in
  http*) curl -fL --retry 3 --retry-delay 5 -o "$WORK/base.dl" "$BASE"
         # نام فایل واقعی از هدر/آدرس نهایی؛ فشرده است یا نه را از محتوا می‌فهمیم
         ;;
  *)     cp "$BASE" "$WORK/base.dl" ;;
esac
if xz -t "$WORK/base.dl" 2>/dev/null; then xz -dc "$WORK/base.dl" > "$IMG"; else mv "$WORK/base.dl" "$IMG"; fi
rm -f "$WORK/base.dl"
echo "اندازه‌ی ایمیج پایه: $(du -h "$IMG" | cut -f1)"

# ── ۲) بزرگ‌کردن پارتیشن ریشه ────────────────────────────────────────────────────────
log "بزرگ‌کردن ایمیج (+${EXTRA_GB}GB)"
truncate -s "+${EXTRA_GB}G" "$IMG"
LOOP=$(losetup -fP --show "$IMG")
PTTYPE=$(parted -s "$LOOP" print 2>/dev/null | awk -F': ' '/Partition Table/ {print $2}')
if [ "$PTTYPE" = gpt ]; then sgdisk -e "$LOOP" >/dev/null 2>&1 || true; fi
# پارتیشن ریشه = آخرین پارتیشن ext4
PART=$(lsblk -nrpo NAME,FSTYPE "$LOOP" | awk '$2=="ext4" {p=$1} END {print p}')
[ -n "$PART" ] || { echo "پارتیشن ext4 پیدا نشد."; lsblk "$LOOP"; exit 1; }
PARTNUM=${PART##*p}
parted -s -- "$LOOP" resizepart "$PARTNUM" 100%
partprobe "$LOOP" 2>/dev/null || true
e2fsck -fy "$PART" || [ $? -le 1 ]
resize2fs "$PART"
mount "$PART" "$ROOT"

# ── ۳) نصب داخل chroot ─────────────────────────────────────────────────────────────
log "آماده‌سازی chroot"
mount -t proc proc "$ROOT/proc"
mount -t sysfs sys "$ROOT/sys"
mount --bind /dev "$ROOT/dev"
mount -t devpts devpts "$ROOT/dev/pts" 2>/dev/null || true
[ -L "$ROOT/etc/resolv.conf" ] && mv "$ROOT/etc/resolv.conf" "$ROOT/etc/resolv.conf.pgpro-orig"
cp /etc/resolv.conf "$ROOT/etc/resolv.conf"

mkdir -p "$ROOT/tmp/pgpro-src"
rsync -a --delete --exclude .git --exclude '*.sqlite3' --exclude staticfiles --exclude .ruff_cache \
  --exclude __pycache__ "$REPO"/ "$ROOT/tmp/pgpro-src/"
mkdir -p "$ROOT/etc/pgpro"
grep -E '^(ssh-|ecdsa-|sk-)' "$KEYS" > "$ROOT/etc/pgpro/support_keys" 2>/dev/null || : > "$ROOT/etc/pgpro/support_keys"
if [ ! -s "$ROOT/etc/pgpro/support_keys" ]; then
  echo "هشدار: هیچ کلید SSH پشتیبانی داده نشده؛ ورود SSH ممکن نخواهد بود (image/support_keys.pub)." >&2
fi

log "install.sh"
chroot "$ROOT" /usr/bin/env PGPRO_VERSION="$VERSION" bash /tmp/pgpro-src/image/overlay/install.sh

if [ "${PGPRO_SKIP_SMOKE:-0}" != 1 ]; then
  log "آزمون دود"
  chroot "$ROOT" /usr/bin/env LANG=C.UTF-8 bash /tmp/pgpro-src/image/overlay/smoke.sh
fi

# ── ۴) تمیزکاری ───────────────────────────────────────────────────────────────────
log "تمیزکاری"
rm -rf "$ROOT/tmp/pgpro-src" "$ROOT/root/.cache" "$ROOT/var/lib/apt/lists"/* "$ROOT/var/cache/apt"/*
find "$ROOT/var/log" -type f -exec truncate -s 0 {} + 2>/dev/null || true
rm -f "$ROOT/etc/resolv.conf"
[ -e "$ROOT/etc/resolv.conf.pgpro-orig" ] && mv "$ROOT/etc/resolv.conf.pgpro-orig" "$ROOT/etc/resolv.conf"
rm -f "$ROOT/root/.bash_history" "$ROOT/home/support/.bash_history"
for m in dev/pts dev proc sys; do umount -lf "$ROOT/$m" 2>/dev/null || true; done
sync

# ── ۵) کوچک‌کردن (فقط جدول msdos؛ Armbian در اولین بوت دوباره تا آخر کارت بزرگ می‌کند) ─────────────────────
if [ "$PTTYPE" != gpt ]; then
  log "کوچک‌کردن"
  umount "$ROOT"
  e2fsck -fy "$PART" || [ $? -le 1 ]
  resize2fs -M "$PART"
  BLOCKS=$(dumpe2fs -h "$PART" 2>/dev/null | awk -F: '/^Block count/ {gsub(/ /,"",$2); print $2}')
  BSIZE=$(dumpe2fs -h "$PART" 2>/dev/null | awk -F: '/^Block size/ {gsub(/ /,"",$2); print $2}')
  START=$(parted -sm "$LOOP" unit s print | awk -F: -v n="$PARTNUM" '$1==n {gsub(/s/,"",$2); print $2}')
  END=$(( START + BLOCKS * BSIZE / 512 + 2048 ))
  parted -s -- "$LOOP" resizepart "$PARTNUM" "${END}s"
  losetup -d "$LOOP"; LOOP=""
  truncate -s $(( (END + 1) * 512 + 1048576 )) "$IMG"
else
  umount "$ROOT"
  losetup -d "$LOOP"; LOOP=""
fi

# ── ۶) خروجی ──────────────────────────────────────────────────────────────────────
log "فشرده‌سازی"
mv "$IMG" "$OUT/$NAME.img"
( cd "$OUT" && xz -T0 -6 -f "$NAME.img" && sha256sum "$NAME.img.xz" > "$NAME.img.xz.sha256" )
rm -rf "$WORK"
ls -lh "$OUT"
echo "آماده: $OUT/$NAME.img.xz"
