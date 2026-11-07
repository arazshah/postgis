# سایت استاتیک pgpro.ir (nginx). ساخت: docker build -t pgpro-site pgpro-site
FROM nginx:1.27-alpine

RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY public/ /usr/share/nginx/html/

# مقصد هدایت /update/* (Release گیت‌هاب با برچسب pgpro-latest)
ENV PGPRO_RELEASE_BASE=https://github.com/arazshah/postgis/releases/download/pgpro-latest

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
