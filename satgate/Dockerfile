# دروازه‌ی ماهواره؛ context بیلد = ریشه‌ی مخزن:
#   docker build -f satgate/Dockerfile -t satgate .
ARG BASE_IMAGE=python:3.13-slim
FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 SATGATE_DATA=/data
WORKDIR /app
COPY satgate/requirements.txt satgate/requirements.txt
RUN pip install -r satgate/requirements.txt && useradd --create-home --uid 1000 sat && mkdir /data && chown sat /data
COPY satgate/*.py satgate/
USER sat
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/v1/health', timeout=4)"
# یک پردازش و چند رشته: صف کارها در حافظه‌ی همین پردازش است
CMD ["gunicorn", "satgate.app:application", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "--timeout", "120"]
