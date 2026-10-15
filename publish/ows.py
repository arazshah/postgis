"""
WMS / WFS با QGIS Server.

کاربر پروژه‌اش را در QGIS دسکتاپ می‌سازد و آپلود می‌کند (یا در خود پایگاه داده ذخیره می‌کند). پنل آن را پاک
می‌کند (publish/qgis.py)، اتصال لایه‌ها را به نقش فقط‌خواندنی <role>_ows می‌برد و فایل نهایی را روی پوشه
مشترک با کانتینر QGIS Server می‌نویسد. همه درخواست‌ها از /ows/<slug>/ و همین Django می‌گذرند: بررسی
عمومی/کلید، سقف روزانه پلن، فهرست درخواست‌های مجاز، و بعد پراکسی به QGIS Server داخلی.
"""
from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.views.decorators.http import require_http_methods
from psycopg import sql

from core.templatetags.fa import fanum
from databases import crypto
from databases.explorer import Explorer, ExplorerError
from databases.provisioner import Provisioner, ProvisionError

from . import access, qgis
from .models import OwsProject, Service

log = logging.getLogger(__name__)

ALLOWED = {
    "WMS": {"GETCAPABILITIES", "GETMAP", "GETFEATUREINFO", "GETLEGENDGRAPHIC", "DESCRIBELAYER", "GETSTYLES"},
    "WFS": {"GETCAPABILITIES", "DESCRIBEFEATURETYPE", "GETFEATURE"},
}
DROP_PARAMS = {"MAP", "KEY", "FILE_NAME"}
WFS_MAX_FEATURES = 10_000
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
CACHE_TTL = 300


class OwsError(Exception):
    pass


# ---------------------------------------------------------------------- نقش فقط‌خواندنی و فایل‌ها
def ows_password(service: Service, force: bool = False) -> str:
    if service.ows_password_encrypted and not force:
        return crypto.decrypt(service.ows_password_encrypted)
    db = service.database
    password = crypto.generate_password(28)
    try:
        prov = Provisioner.for_server(db.server)
        prov.harden()  # پیش از ساخت نقش عضو pg_read_all_data: هیچ دیتابیسی برای PUBLIC باز نماند
        prov.ensure_ows_role(db.db_name, db.role_name, password)
    except ProvisionError as exc:
        raise OwsError(f"آماده‌سازی دسترسی فقط‌خواندنی ممکن نشد: {exc}") from exc
    service.ows_password_encrypted = crypto.encrypt(password)
    service.save(update_fields=["ows_password_encrypted"])
    return password


def connection(service: Service, force: bool = False) -> str:
    db = service.database
    server = db.server
    return qgis.connection_string(server.host, server.port, db.db_name, Provisioner.ows_role_name(db.role_name),
                                  ows_password(service, force), server.sslmode)


def public_url(project: OwsProject) -> str:
    return settings.SITE_URL.rstrip("/") + f"/ows/{project.slug}/"


def project_path(project: OwsProject) -> Path:
    return Path(settings.OWS_ROOT) / project.service.slug / f"{project.slug}.qgs"


def write_file(project: OwsProject, force_password: bool = False) -> Path:
    path = project_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    xml = qgis.render(project.xml, connection(project.service, force_password))
    xml = _with_urls(xml, public_url(project))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(xml, encoding="utf-8")
    os.chmod(tmp, 0o640)
    tmp.replace(path)
    return path


def _with_urls(xml: str, url: str) -> str:
    """آدرس عمومی سرویس در GetCapabilities (به‌جای آدرس داخلی QGIS Server)."""
    from xml.sax.saxutils import escape

    props = f'<WMSUrl type="QString">{escape(url)}</WMSUrl><WFSUrl type="QString">{escape(url)}</WFSUrl>'
    return xml.replace("<properties>", "<properties>" + props, 1)


def ensure_file(project: OwsProject) -> Path:
    path = project_path(project)
    if not path.exists() or path.stat().st_mtime < project.updated_at.timestamp():
        write_file(project)
    return path


def rewrite_all(service: Service):
    """بعد از تغییر رمز نقش _ows (مثلاً بازگردانی بکاپ)، همه فایل‌ها دوباره نوشته می‌شوند."""
    for p in service.ows_projects.all():
        write_file(p)


def remove_file(project: OwsProject):
    project_path(project).unlink(missing_ok=True)


def remove_service_files(service: Service):
    folder = Path(settings.OWS_ROOT) / service.slug
    if folder.is_dir():
        for f in folder.glob("*"):
            f.unlink(missing_ok=True)
        folder.rmdir()


# ---------------------------------------------------------------------- ساخت پروژه
def _missing_tables(db, layers: list[qgis.LayerInfo]) -> list[str]:
    try:
        tables = {(t.schema, t.name) for t in Explorer(db).tables()}
    except ExplorerError:
        return []
    return [f"لایه «{x.name}» به جدول {x.schema}.{x.table} اشاره می‌کند که در این پایگاه داده نیست؛ "
            "روی نقشه خالی می‌ماند." for x in layers if (x.schema, x.table) not in tables]


def _bbox(db, layers: list[qgis.LayerInfo]) -> list[float]:
    """محدوده همه لایه‌های برداری به طول و عرض جغرافیایی (برای پیش‌نمایش)."""
    boxes = []
    try:
        with Explorer(db).connect() as conn:
            for x in layers:
                if x.kind != "vector" or not x.geom_column:
                    continue
                g, t = sql.Identifier(x.geom_column), sql.Identifier(x.schema, x.table)
                try:
                    row = conn.execute(sql.SQL(
                        "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM (SELECT ST_Transform("
                        "ST_SetSRID(ST_Extent({g}), (SELECT ST_SRID({g}) FROM {t} WHERE {g} IS NOT NULL LIMIT 1)),"
                        " 4326) AS e FROM {t}) s").format(g=g, t=t)).fetchone()
                except Exception:  # noqa: BLE001  جدول نیست یا SRID ندارد
                    conn.rollback()
                    continue
                if row and row[0] is not None:
                    boxes.append(row)
    except ExplorerError:
        return []
    if not boxes:
        return []
    return [round(min(b[0] for b in boxes), 6), round(min(b[1] for b in boxes), 6),
            round(max(b[2] for b in boxes), 6), round(max(b[3] for b in boxes), 6)]


def _apply(project: OwsProject, data: bytes, filename: str = "") -> OwsProject:
    xml_bytes = qgis.read_project_bytes(data, filename)
    result = qgis.sanitize(xml_bytes, title=project.title, wfs=project.wfs_enabled)
    db = project.service.database
    project.xml = result.xml
    project.title = project.title or result.title[:120]
    project.layers = [{"name": x.name, "kind": x.kind, "schema": x.schema, "table": x.table,
                       "geom_type": x.geom_type} for x in result.layers]
    project.warnings = result.warnings + _missing_tables(db, result.layers)
    project.bbox = _bbox(db, result.layers)
    project.save()
    write_file(project)
    return project


def create_project(db, data: bytes, filename: str, *, title: str = "", is_public: bool = False,
                   source: str = OwsProject.Source.UPLOAD, schema: str = "") -> OwsProject:
    service, _ = Service.objects.get_or_create(database=db)
    if service.ows_projects.count() >= db.plan.ows_projects:
        raise OwsError(f"پلن شما حداکثر {fanum(db.plan.ows_projects)} پروژه WMS/WFS دارد. یک پروژه را حذف یا پلن را "
                       "ارتقا دهید.")
    project = OwsProject(service=service, title=title[:120], is_public=is_public, source=source,
                         source_name=filename[:255], source_schema=schema)
    try:
        return _apply(project, data, filename)
    except Exception:
        if project.pk:
            project.delete()
        raise


def update_settings(project: OwsProject, *, title: str, is_public: bool, wfs: bool):
    project.title = title[:120] or project.title
    project.is_public = is_public
    if wfs != project.wfs_enabled:
        project.wfs_enabled = wfs
        result = qgis.sanitize(project.xml.encode(), title=project.title, wfs=wfs)
        project.xml = result.xml
    project.save()
    write_file(project)


# ---------------------------------------------------------------------- پروژه‌های ذخیره‌شده در پایگاه داده
def saved_projects(db) -> list[dict]:
    """پروژه‌هایی که با Project › Save To › PostgreSQL در QGIS ذخیره شده‌اند (جدول qgis_projects)."""
    out = []
    try:
        with Explorer(db).connect() as conn:
            schemas = [r[0] for r in conn.execute("""
                SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = 'qgis_projects' AND c.relkind = 'r' AND has_table_privilege(c.oid, 'SELECT')
            """).fetchall()]
            for schema in schemas:
                q = sql.SQL("SELECT name, metadata->>'last_modified_time', length(content) FROM {} ORDER BY name"
                            ).format(sql.Identifier(schema, "qgis_projects"))
                for name, modified, size in conn.execute(q).fetchall():
                    out.append({"schema": schema, "name": name, "modified": modified, "size": size})
    except Exception as exc:  # noqa: BLE001  اتصال یا ساختار جدول غیرمنتظره
        log.info("saved_projects %s: %s", db.pk, exc)
    return out


def read_saved(db, schema: str, name: str) -> bytes:
    with Explorer(db).connect() as conn:
        q = sql.SQL("SELECT content FROM {} WHERE name = %s").format(sql.Identifier(schema, "qgis_projects"))
        row = conn.execute(q, (name,)).fetchone()
    if not row:
        raise OwsError("این پروژه در پایگاه داده پیدا نشد.")
    return bytes(row[0])


def refresh_from_database(project: OwsProject) -> OwsProject:
    data = read_saved(project.service.database, project.source_schema, project.source_name)
    return _apply(project, data, project.source_name + ".qgz")


# ---------------------------------------------------------------------- پراکسی
def _exception(message: str, status: int, code: str = "InvalidParameterValue") -> HttpResponse:
    from xml.sax.saxutils import escape

    body = ('<?xml version="1.0" encoding="UTF-8"?>\n<ServiceExceptionReport version="1.3.0" '
            'xmlns="http://www.opengis.net/ogc">'
            f'<ServiceException code="{code}">{escape(message)}</ServiceException></ServiceExceptionReport>')
    resp = HttpResponse(body, status=status, content_type="text/xml; charset=utf-8")
    resp["Cache-Control"] = "no-store"
    return _cors(resp)


def _cors(resp):
    resp["Access-Control-Allow-Origin"] = "*"
    resp["Access-Control-Allow-Headers"] = "Authorization, X-API-Key"
    resp["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return resp


def _params(request) -> dict[str, str]:
    return {k.upper(): v for k, v in request.GET.items() if k.upper() not in DROP_PARAMS}


def _fetch(url: str, headers: dict) -> tuple[int, str, bytes]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=settings.QGIS_SERVER_TIMEOUT) as r:  # noqa: S310 آدرس داخلی ثابت
            body = r.read(MAX_RESPONSE_BYTES + 1)
            return r.status, r.headers.get("Content-Type", "application/octet-stream"), body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "text/xml"), exc.read(1024 * 1024)


@require_http_methods(["GET", "HEAD", "OPTIONS"])
def ows(request, slug):
    if request.method == "OPTIONS":
        return _cors(HttpResponse(status=204))
    project = OwsProject.objects.select_related("service__database__plan", "service__database__server").filter(
        slug=slug).first()
    if project is None:
        return _exception("این سرویس پیدا نشد.", 404, "NotFound")
    db = project.service.database
    params = _params(request)
    service_name = params.get("SERVICE", "").upper()
    req_name = params.get("REQUEST", "").upper()
    if service_name not in ALLOWED:
        return _exception("پارامتر SERVICE باید WMS یا WFS باشد.", 400, "MissingParameterValue")
    if service_name == "WFS" and not project.wfs_enabled:
        return _exception("WFS برای این پروژه خاموش است.", 400, "OperationNotSupported")
    if req_name not in ALLOWED[service_name]:
        return _exception(f"درخواست {req_name or '(خالی)'} در این سرویس مجاز نیست.", 400, "OperationNotSupported")
    try:
        access.check_database(db)
        owner = access.is_owner(request, db)
        if not (project.is_public or owner):
            if access.raw_key(request) == "":
                return _exception("این سرویس خصوصی است؛ کلید API را با ?key= یا رمز (Basic) بفرستید.", 401,
                                  "Unauthorized")
            if access.key_for(request, db) is None:
                return _exception("کلید API نامعتبر است، باطل شده یا مال این پایگاه داده نیست.", 403, "Forbidden")
        if not owner:
            access.count(db)
    except access.Denied as exc:
        return _exception(exc.message, exc.status, exc.code)

    for k in ("FILTER", "EXP_FILTER", "SELECTION"):
        if any(bad in params.get(k, "") for bad in (";", "--", "/*")):
            return _exception(f"پارامتر {k} نامعتبر است.", 400)
    if service_name == "WFS" and req_name == "GETFEATURE":
        for k in ("MAXFEATURES", "COUNT"):
            if k in params:
                try:
                    params[k] = str(max(1, min(int(params[k]), WFS_MAX_FEATURES)))
                except ValueError:
                    return _exception(f"{k} باید عدد باشد.", 400)
        if "MAXFEATURES" not in params and "COUNT" not in params:
            params["MAXFEATURES"] = str(WFS_MAX_FEATURES)

    cacheable = req_name in ("GETCAPABILITIES", "GETLEGENDGRAPHIC", "DESCRIBEFEATURETYPE")
    key = request.GET.get("key", "")
    ck = f"ows:{project.pk}:{int(project.updated_at.timestamp())}:{urlencode(sorted(params.items()))}"
    hit = cache.get(ck) if cacheable else None
    if hit:
        status, ctype, body = hit
    else:
        try:
            path = ensure_file(project)
        except (OwsError, OSError) as exc:
            log.exception("ows file %s", slug)
            return _exception(f"آماده‌سازی پروژه ممکن نشد: {exc}", 503, "ServiceUnavailable")
        upstream = settings.QGIS_SERVER_URL + "?" + urlencode({**params, "MAP": str(path)})
        try:
            status, ctype, body = _fetch(upstream, {"X-Qgis-Service-Url": public_url(project)})
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            log.warning("qgis server %s: %s", slug, exc)
            return _exception("سرور نقشه پاسخ نداد؛ چند لحظه بعد دوباره تلاش کنید.", 504, "ServiceUnavailable")
        if len(body) > MAX_RESPONSE_BYTES:
            return _exception("پاسخ خیلی بزرگ است؛ محدوده یا تعداد عوارض را کم کنید.", 413, "ResponseTooLarge")
        if cacheable and status == 200:
            cache.set(ck, (status, ctype, body), CACHE_TTL)
    if key and req_name == "GETCAPABILITIES" and status == 200:
        body = _keep_key(body, public_url(project), key)
    resp = HttpResponse(body, status=status, content_type=ctype)
    resp["Cache-Control"] = ("public, max-age=60" if project.is_public and status == 200
                             else "private, max-age=0, no-store")
    return _cors(resp)


def _keep_key(body: bytes, base: str, key: str) -> bytes:
    """وقتی کلید با ?key آمده، آدرس‌های داخل GetCapabilities هم کلید را داشته باشند."""
    from urllib.parse import quote
    from xml.sax.saxutils import escape

    b = escape(base).encode()
    k = quote(key, safe="").encode()
    body = body.replace(b + b"?", b + b"?key=" + k + b"&amp;")
    return body.replace(b + b'"', b + b"?key=" + k + b'"')
