# QGIS Server (WMS/WFS) برای پروژه‌های کاربران؛ فقط از داخل شبکه compose و از طریق Django در دسترس است.
# پروژه‌ها را پنل در /app/ows می‌نویسد (volume مشترک، اینجا فقط‌خواندنی).
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    QT_QPA_PLATFORM=offscreen \
    QGIS_SERVER_LOG_STDERR=1 \
    QGIS_SERVER_LOG_LEVEL=1 \
    QGIS_SERVER_IGNORE_BAD_LAYERS=true \
    QGIS_SERVER_TRUST_LAYER_METADATA=true \
    QGIS_SERVER_FORCE_READONLY_LAYERS=true \
    QGIS_SERVER_DISABLE_GETPRINT=true \
    QGIS_SERVER_WMS_MAX_WIDTH=4096 \
    QGIS_SERVER_WMS_MAX_HEIGHT=4096 \
    QGIS_SERVER_PROJECT_CACHE_STRATEGY=filesystem \
    QGIS_SERVER_MAX_THREADS=2 \
    QGIS_PROCESSES=2

RUN apt-get update \
 && apt-get install -y --no-install-recommends qgis-server-bin qgis-server-wms qgis-server-wfs \
      spawn-fcgi multiwatch nginx-light fonts-vazirmatn fonts-dejavu-core ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && rm -f /usr/lib/cgi-bin/admin.sld /usr/lib/cgi-bin/wms_metadata.xml

COPY nginx.conf /etc/nginx/nginx.conf
COPY fonts.conf /etc/fonts/local.conf
COPY start.sh /start.sh
RUN chmod +x /start.sh && fc-cache -f >/dev/null

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1/health || exit 1
CMD ["/start.sh"]
