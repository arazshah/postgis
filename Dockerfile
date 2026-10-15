# برای سرورهای داخل ایران که به Docker Hub یا PyPI دسترسی محدود دارند،
# در Coolify این Build Argها را به آینه داخلی تغییر دهید.
ARG BASE_IMAGE=python:3.13-slim
FROM ${BASE_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl postgresql-client gdal-bin \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 app

COPY requirements.txt .
RUN pip install --index-url "$PIP_INDEX_URL" -r requirements.txt

COPY . .
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
 && chmod +x docker/entrypoint.sh \
 && mkdir -p /app/media \
 && chown -R app:app /app

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY:-3} --worker-class gthread --threads ${WEB_THREADS:-4} --timeout 120 --access-logfile -"]
