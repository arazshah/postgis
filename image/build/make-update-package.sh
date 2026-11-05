#!/usr/bin/env bash
# ساخت بسته‌ی به‌روزرسانی pgpro (برای pgpro-update): کد آماده‌ی یک نسخه + فایل‌های سیستم، فشرده.
#   make-update-package.sh <پوشه‌ی release نصب‌شده> <پوشه‌ی rootfs> <نسخه> <پوشه‌ی خروجی>
# خروجی: pgpro-update-<نسخه>.tar.xz و .sha256 (و در صورت وجود کلید امضا PGPRO_UPDATE_SIGN_KEY: .sha256.sig).
set -euo pipefail
REL=${1:?پوشه‌ی release}; ROOTFS=${2:?پوشه‌ی rootfs}; VERSION=${3:?نسخه}; OUT=${4:?پوشه‌ی خروجی}
NAME=pgpro-update-$VERSION.tar.xz
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$OUT"
# ویدیوهای راهنما (~۱۱۰ مگابایت، بدون تغییر بین نسخه‌ها) در بسته نمی‌آیند؛ pgpro-update از نسخه‌ی نصب‌شده هاردلینک می‌کند.
# برای عوض کردن آن‌ها ایمیج کامل لازم است (یا PGPRO_PKG_WITH_HELP=1).
cp -a "$REL" "$STAGE/release"
if [ "${PGPRO_PKG_WITH_HELP:-0}" != 1 ]; then rm -rf "$STAGE/release/staticfiles/help"; fi
cp -a "$ROOTFS" "$STAGE/rootfs"
python3 - "$STAGE/meta.json" "$VERSION" "$(sha256sum "$REL/requirements.txt" | awk '{print $1}')" <<'PY'
import json, sys, time
json.dump({"version": sys.argv[2], "requirements_sha256": sys.argv[3], "created": int(time.time())},
          open(sys.argv[1], "w"), ensure_ascii=False)
PY
tar -C "$STAGE" -cf - release rootfs meta.json | xz -T0 -6 > "$OUT/$NAME"
( cd "$OUT" && sha256sum "$NAME" > "$NAME.sha256" )
if [ -n "${PGPRO_UPDATE_SIGN_KEY:-}" ] && [ -f "$PGPRO_UPDATE_SIGN_KEY" ]; then
  openssl pkeyutl -sign -rawin -inkey "$PGPRO_UPDATE_SIGN_KEY" -in "$OUT/$NAME.sha256" -out "$OUT/$NAME.sha256.sig"
fi
ls -lh "$OUT/$NAME"
