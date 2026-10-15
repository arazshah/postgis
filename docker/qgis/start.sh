#!/bin/sh
# پروسه‌های QGIS Server با کاربر 1000 (همان کاربر app که فایل‌های پروژه را می‌نویسد) و nginx جلوی آن‌ها.
set -e
mkdir -p /tmp/qgis-home && chown 1000:1000 /tmp/qgis-home
rm -f /tmp/qgis.sock
HOME=/tmp/qgis-home spawn-fcgi -s /tmp/qgis.sock -M 0660 -u 1000 -g 33 -- \
  /usr/bin/multiwatch -f "${QGIS_PROCESSES:-2}" -- /usr/lib/cgi-bin/qgis_mapserv.fcgi
exec nginx -g 'daemon off;'
