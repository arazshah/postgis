"""
GeoServer اختصاصی برای پلن سازمانی: هر مشتری کانتینر جدای خودش را دارد (نه GeoServer مشترک).

- ساخت کانتینر با API سرویس Coolify (اگر COOLIFY_API_URL و توکن تنظیم شده باشد)؛ وگرنه مدیر دستی می‌سازد و
  آدرس و رمز را در پنل مدیریت وارد می‌کند.
- پیکربندی با REST API خود GeoServer: workspace هم‌نام پایگاه داده و یک datastore از نوع PostGIS با کاربر
  فقط‌خواندنی جداگانه (نه رمز اصلی مشتری)؛ و انتشار همه جدول‌های مکانی به‌صورت لایه.
"""
from __future__ import annotations

import base64
import json
import secrets
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from django.conf import settings

ROLE_SUFFIX = "geoserver"


class GeoServerError(Exception):
    pass


# ---------------------------------------------------------------------- HTTP
def _request(method: str, url: str, *, body=None, headers=None, auth: tuple[str, str] | None = None,
             timeout: int = 30) -> tuple[int, bytes]:
    data = None
    hdrs = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    if auth:
        hdrs["Authorization"] = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 آدرس از تنظیمات مدیر
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GeoServerError(f"اتصال به {url.split('/')[2]} ممکن نشد: {exc}") from exc


# ---------------------------------------------------------------------- Coolify
def coolify_enabled() -> bool:
    return bool(settings.COOLIFY_API_URL and settings.COOLIFY_API_TOKEN and settings.COOLIFY_PROJECT_UUID
                and settings.COOLIFY_SERVER_UUID and settings.GEOSERVER_DOMAIN)


def _coolify(method: str, path: str, body=None) -> dict:
    status, raw = _request(method, settings.COOLIFY_API_URL.rstrip("/") + path, body=body,
                           headers={"Authorization": f"Bearer {settings.COOLIFY_API_TOKEN}"}, timeout=60)
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        data = {"raw": raw[:300].decode(errors="replace")}
    if status >= 300:
        raise GeoServerError(f"Coolify {path}: {status} {str(data)[:300]}")
    return data


def create_container(instance) -> None:
    """برنامه Docker image در Coolify با دامنه جدا؛ رمز مدیر GeoServer تصادفی."""
    host = f"gs-{instance.slug}.{settings.GEOSERVER_DOMAIN}"
    password = secrets.token_urlsafe(18)
    app = _coolify("POST", "/api/v1/applications/dockerimage", {
        "project_uuid": settings.COOLIFY_PROJECT_UUID, "server_uuid": settings.COOLIFY_SERVER_UUID,
        "environment_name": settings.COOLIFY_ENVIRONMENT, "name": f"geoserver-{instance.slug}",
        "docker_registry_image_name": settings.GEOSERVER_IMAGE.split(":")[0],
        "docker_registry_image_tag": (settings.GEOSERVER_IMAGE.split(":") + ["latest"])[1],
        "ports_exposes": "8080", "domains": f"https://{host}", "instant_deploy": False,
        "limits_memory": f"{instance.memory_mb}m", "limits_cpus": "1",
    })
    uuid = app.get("uuid") or app.get("id")
    if not uuid:
        raise GeoServerError(f"پاسخ Coolify شناسه برنامه نداشت: {str(app)[:200]}")
    for key, value in (("GEOSERVER_ADMIN_USER", "admin"), ("GEOSERVER_ADMIN_PASSWORD", password),
                       ("SKIP_DEMO_DATA", "true"), ("CORS_ENABLED", "true"),
                       ("EXTRA_JAVA_OPTS", f"-Xms256m -Xmx{max(512, instance.memory_mb - 256)}m")):
        _coolify("POST", f"/api/v1/applications/{uuid}/envs", {"key": key, "value": value, "is_preview": False})
    _coolify("GET", f"/api/v1/deploy?uuid={uuid}&force=false")
    instance.coolify_uuid = str(uuid)
    instance.url = f"https://{host}/geoserver"
    instance.admin_user = "admin"
    instance.set_password(password)


def stop_container(instance) -> None:
    if instance.coolify_uuid and coolify_enabled():
        _coolify("POST", f"/api/v1/applications/{instance.coolify_uuid}/stop")


# ---------------------------------------------------------------------- GeoServer REST
def _gs(instance, method: str, path: str, body=None) -> tuple[int, bytes]:
    return _request(method, instance.url.rstrip("/") + "/rest" + path, body=body,
                    auth=(instance.admin_user, instance.get_password()))


def wait_until_up(instance, timeout_s: int = 600, interval: int = 10) -> str:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        try:
            status, raw = _gs(instance, "GET", "/about/version.json")
            if status == 200:
                about = json.loads(raw)
                for r in about.get("about", {}).get("resource", []):
                    if r.get("@name") == "GeoServer":
                        return str(r.get("Version", ""))
                return "?"
            last = f"HTTP {status}"
        except (GeoServerError, ValueError) as exc:
            last = str(exc)
        time.sleep(interval)
    raise GeoServerError(f"GeoServer در {timeout_s // 60} دقیقه بالا نیامد ({last}).")


def bootstrap(instance, role_name: str, role_password: str) -> dict:
    """workspace + datastore + انتشار جدول‌های مکانی. چندباره اجراشدنی است."""
    from databases.explorer import Explorer

    db = instance.database
    server = db.server
    ws = db.db_name
    status, _ = _gs(instance, "GET", f"/workspaces/{quote(ws)}.json")
    if status == 404:
        status, raw = _gs(instance, "POST", "/workspaces", {"workspace": {"name": ws}})
        if status >= 300:
            raise GeoServerError(f"ساخت workspace ناموفق بود: {status} {raw[:200]!r}")
    params = {"host": server.host, "port": str(server.port), "database": db.db_name, "user": role_name,
              "passwd": role_password, "dbtype": "postgis", "schema": "public", "Expose primary keys": "true",
              "SSL mode": {"disable": "DISABLE", "require": "REQUIRE"}.get(server.sslmode, "ALLOW"),
              "max connections": "4", "min connections": "1", "Loose bbox": "true", "Estimated extends": "true"}
    store = {"dataStore": {"name": "postgis", "connectionParameters": {
        "entry": [{"@key": k, "$": v} for k, v in params.items()]}}}
    status, _ = _gs(instance, "GET", f"/workspaces/{quote(ws)}/datastores/postgis.json")
    if status == 404:
        status, raw = _gs(instance, "POST", f"/workspaces/{quote(ws)}/datastores", store)
    else:
        status, raw = _gs(instance, "PUT", f"/workspaces/{quote(ws)}/datastores/postgis", store)
    if status >= 300:
        raise GeoServerError(f"ساخت اتصال PostGIS در GeoServer ناموفق بود: {status} {raw[:200]!r}")
    published, failed = [], []
    for t in Explorer(db).tables():
        if t.schema != "public" or not t.geometry or t.kind not in ("r", "v", "m", "p"):
            continue
        status, _ = _gs(instance, "GET", f"/workspaces/{quote(ws)}/datastores/postgis/featuretypes/{quote(t.name)}.json")
        if status == 200:
            published.append(t.name)
            continue
        status, raw = _gs(instance, "POST", f"/workspaces/{quote(ws)}/datastores/postgis/featuretypes",
                          {"featureType": {"name": t.name, "nativeName": t.name, "title": t.name}})
        (published if status < 300 else failed).append(t.name)
    return {"workspace": ws, "published": published, "failed": failed}
