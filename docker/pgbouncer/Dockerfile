# PgBouncer جلوی سرور PostGIS مشتریان (اختیاری؛ در docker-compose با profile «pooler»)
ARG BASE_IMAGE=debian:bookworm-slim
FROM ${BASE_IMAGE}
RUN apt-get update \
 && apt-get install -y --no-install-recommends pgbouncer gettext-base openssl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /etc/pgbouncer /var/run/postgresql \
 && chown -R postgres:postgres /etc/pgbouncer /var/run/postgresql
COPY pgbouncer.ini.tmpl /pgbouncer.ini.tmpl
COPY start.sh /start.sh
USER postgres
EXPOSE 6432
HEALTHCHECK --interval=30s --timeout=5s CMD ["bash", "-c", "test -f /tmp/pgbouncer.disabled || exec 3<>/dev/tcp/127.0.0.1/6432"]
ENTRYPOINT ["/start.sh"]
