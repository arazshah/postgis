#!/usr/bin/env bash
# ساخت echarts.min.js سفارشی: bash static/vendor/echarts/build.sh  (نیاز به npm و دسترسی به registry)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
work="$(mktemp -d)"
cp "$here/src/entry.js" "$work/entry.js"
cd "$work"
npm init -y >/dev/null
npm install --silent echarts@5.5.1 esbuild@0.24.0
npx esbuild entry.js --bundle --minify --format=iife --legal-comments=none --outfile="$here/echarts.min.js"
ls -la "$here/echarts.min.js"
