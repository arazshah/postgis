"""
آماده‌سازی پروژه QGIS کاربر برای QGIS Server.

پروژه‌ای که کاربر در QGIS دسکتاپ ساخته (فایل .qgs/.qgz یا ذخیره‌شده در خود پایگاه داده) به سرور می‌آید.
قبل از اینکه QGIS Server آن را باز کند:

- فقط لایه‌های PostGIS (postgres و postgresraster) می‌مانند؛ فایل محلی، WMS/XYZ، لایه مجازی، افزونه‌ای و
  … حذف می‌شوند (سرور نباید فایل‌های خودش را بخواند یا به آدرس دلخواه درخواست بفرستد).
- اتصال هر لایه بازنویسی می‌شود: همیشه به پایگاه داده همین کاربر و با نقش فقط‌خواندنی <role>_ows،
  هر میزبان، کاربر، رمز، service یا authcfg که در فایل بوده دور ریخته می‌شود.
- ماکروهای پایتون، توابع عبارت سفارشی، لایه‌های جاسازی‌شده از پروژه دیگر و تنظیمات WFS-T حذف می‌شوند.

نسخه پاک‌شده (بدون رمز) در پنل نگه داشته می‌شود و فایل نهایی با رمز نقش _ows فقط روی دیسک مشترک با
QGIS Server نوشته می‌شود.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.sax.saxutils import escape as xml_escape

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

MAX_PROJECT_BYTES = 20 * 1024 * 1024
ALLOWED_PROVIDERS = {"postgres", "postgresraster"}
CONN_KEYS = {"dbname", "host", "hostaddr", "port", "user", "username", "password", "service", "authcfg",
             "sslmode", "sslcert", "sslkey", "sslrootcert", "options", "connect_timeout", "application_name"}
KEEP_KEYS = {"key", "srid", "type", "checkPrimaryKeyUnicity", "estimatedmetadata", "selectatid", "mode",
             "tablename", "geometrycolumn", "temporalDefaultTime", "temporalFieldIndex", "column", "where",
             "bandIndex"}
PLACEHOLDER = "__GP_CONNECTION__"
ROOT_NAME = "all"
PROVIDER_NAMES = {"wms": "WMS/XYZ (نقشه پایه از اینترنت)", "ogr": "فایل (Shapefile، GeoPackage …)",
                  "gdal": "فایل رستر", "delimitedtext": "فایل CSV", "virtual": "لایه مجازی",
                  "spatialite": "SpatiaLite", "memory": "لایه موقت (Scratch)", "arcgisfeatureserver": "ArcGIS",
                  "wfs": "WFS", "vectortile": "کاشی برداری", "mdal": "Mesh", "": "بدون منبع"}


class ProjectError(Exception):
    pass


@dataclass
class LayerInfo:
    id: str
    name: str
    kind: str  # vector | raster
    schema: str = ""
    table: str = ""
    geom_column: str = ""
    geom_type: str = ""


@dataclass
class Sanitized:
    xml: str
    title: str
    layers: list[LayerInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------- خواندن فایل
def read_project_bytes(data: bytes, filename: str = "") -> bytes:
    """محتوای XML پروژه از .qgs یا .qgz (zip)."""
    if len(data) > MAX_PROJECT_BYTES:
        raise ProjectError("حجم پروژه بیشتر از ۲۰ مگابایت است.")
    if data[:2] == b"PK" or filename.lower().endswith(".qgz"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = [n for n in zf.namelist() if n.lower().endswith(".qgs") and "/" not in n.strip("/")]
                if not names:
                    raise ProjectError("داخل فایل qgz پروژه‌ای (.qgs) پیدا نشد.")
                info = zf.getinfo(names[0])
                if info.file_size > MAX_PROJECT_BYTES:
                    raise ProjectError("حجم پروژه بیشتر از ۲۰ مگابایت است.")
                return zf.read(info)
        except zipfile.BadZipFile as exc:
            raise ProjectError("فایل qgz خراب است.") from exc
    return data


# ---------------------------------------------------------------------- رشته اتصال QGIS
_TOKEN = re.compile(r"\s*([A-Za-z_]+)=('(?:[^'\\]|\\.)*'|\S*)")
_TABLE = re.compile(r'\s*table=((?:"(?:[^"]|"")*"\.)?"(?:[^"]|"")*"|\S+)(?:\s*\(([^)]*)\))?')


def _unq(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return re.sub(r"\\(.)", r"\1", v[1:-1])
    return v


def _q(v: str) -> str:
    return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _ident_unq(v: str) -> str:
    return v[1:-1].replace('""', '"') if v.startswith('"') and v.endswith('"') else v


def parse_uri(uri: str) -> dict:
    """رشته منبع داده postgres در QGIS (QgsDataSourceUri) به اجزا. sql= تا آخر رشته است."""
    out: dict = {"params": {}, "schema": "", "table": "", "geom": "", "sql": ""}
    m = re.search(r"(?:^|\s)sql=", uri)
    if m:
        out["sql"] = uri[m.end():]
        uri = uri[:m.start()]
    t = _TABLE.search(uri)
    if t:
        ref = t.group(1)
        parts = re.findall(r'"((?:[^"]|"")*)"', ref)
        if len(parts) == 2:
            out["schema"], out["table"] = (p.replace('""', '"') for p in parts)
        elif len(parts) == 1:
            out["schema"], out["table"] = "public", parts[0].replace('""', '"')
        else:
            out["schema"], out["table"] = "public", ref
        out["geom"] = (t.group(2) or "").strip()
        uri = uri[:t.start()] + " " + uri[t.end():]
    pos = 0
    while pos < len(uri):
        tm = _TOKEN.match(uri, pos)
        if not tm or tm.end() == pos:
            break
        out["params"][tm.group(1)] = _unq(tm.group(2))
        pos = tm.end()
    return out


def build_uri(parsed: dict, conn: str) -> str:
    def ident(v):
        return '"' + v.replace('"', '""') + '"'

    parts = [conn]
    for k, v in parsed["params"].items():
        if k in KEEP_KEYS:
            parts.append(f"{k}={_q(v)}" if k not in ("srid", "type") else f"{k}={v}")
    table = f"table={ident(parsed['schema'] or 'public')}.{ident(parsed['table'])}"
    if parsed["geom"]:
        table += f" ({parsed['geom']})"
    parts.append(table)
    if parsed["sql"]:
        parts.append(f"sql={parsed['sql']}")
    return " ".join(parts)


def connection_string(host: str, port: int, dbname: str, user: str, password: str, sslmode: str) -> str:
    ssl = {"disable": "disable", "allow": "allow", "prefer": "prefer", "require": "require",
           "verify-ca": "verify-ca", "verify-full": "verify-full"}.get(sslmode, "prefer")
    return (f"dbname={_q(dbname)} host={host} port={int(port)} user={_q(user)} password={_q(password)} "
            f"sslmode={ssl}")


# ---------------------------------------------------------------------- پاک‌سازی
def _text(el: Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _set_list(props: Element, name: str, values: list[str]):
    el = props.find(name)
    if el is not None:
        props.remove(el)
    el = SubElement(props, name, {"type": "QStringList"})
    for v in values:
        SubElement(el, "value").text = v


def _set_value(props: Element, name: str, value: str, typ: str = "QString"):
    el = props.find(name)
    if el is None:
        el = SubElement(props, name)
    el.attrib = {"type": typ}
    for c in list(el):
        el.remove(c)
    el.text = value


def sanitize(xml_bytes: bytes, *, title: str = "", wfs: bool = True) -> Sanitized:
    try:
        root = SafeET.fromstring(xml_bytes, forbid_dtd=False, forbid_entities=True, forbid_external=True)
    except DefusedXmlException as exc:
        raise ProjectError("پروژه شامل بخش‌های ناامن XML (entity) است.") from exc
    except SafeET.ParseError as exc:
        raise ProjectError(f"فایل پروژه QGIS خوانا نیست: {exc}") from exc
    if root.tag != "qgis":
        raise ProjectError("این فایل پروژه QGIS نیست.")
    version = root.get("version", "")
    if version and not re.match(r"^3\.", version):
        raise ProjectError(f"پروژه با QGIS {version} ساخته شده؛ فقط پروژه‌های QGIS 3 پشتیبانی می‌شوند.")

    result = Sanitized(xml="", title=title or _text(root.find("title")) or root.get("projectname", "") or "پروژه")
    warnings = result.warnings
    dropped: dict[str, str] = {}
    sources: dict[str, str] = {}

    pl = root.find("projectlayers")
    for ml in list(pl) if pl is not None else []:
        lid = _text(ml.find("id"))
        name = _text(ml.find("layername")) or lid
        provider = _text(ml.find("provider"))
        typ = ml.get("type", "")
        embedded = ml.get("embedded") == "1"
        if embedded or provider not in ALLOWED_PROVIDERS or typ not in ("vector", "raster"):
            pl.remove(ml)
            dropped[lid] = name
            kind = "لایه جاسازی‌شده از پروژه دیگر" if embedded else PROVIDER_NAMES.get(provider, provider or typ)
            warnings.append(f"لایه «{name}» حذف شد: منبع {kind} روی سرور پشتیبانی نمی‌شود؛ "
                            "فقط لایه‌های همین پایگاه داده منتشر می‌شوند.")
            continue
        ds = ml.find("datasource")
        parsed = parse_uri(_text(ds))
        if not parsed["table"]:
            pl.remove(ml)
            dropped[lid] = name
            warnings.append(f"لایه «{name}» حذف شد: جدول منبع آن مشخص نیست.")
            continue
        # نام پایگاه داده، میزبان و کاربر فایل مهم نیست؛ همیشه پایگاه داده همین کاربر
        new = build_uri(parsed, PLACEHOLDER)
        ds.text = new
        sources[lid] = new
        result.layers.append(LayerInfo(
            id=lid, name=name, kind=typ, schema=parsed["schema"], table=parsed["table"], geom_column=parsed["geom"],
            geom_type=ml.get("geometry", "") or parsed["params"].get("type", "")))

    # درخت لایه‌ها و هر ارجاع دیگر به منبع
    for parent in root.iter():
        for child in list(parent):
            if child.tag == "layer-tree-layer":
                lid = child.get("id", "")
                if lid in dropped or (lid not in sources and child.get("providerKey") not in (None, "")):
                    parent.remove(child)
                elif lid in sources:
                    child.set("source", sources[lid])
            elif child.tag == "layer-tree-group" and child.get("embedded") == "1":
                parent.remove(child)
                warnings.append(f"گروه «{child.get('name', '')}» از پروژه دیگری جاسازی شده بود و حذف شد.")
    lo = root.find("layerorder")
    if lo is not None:
        for c in list(lo):
            if c.get("id") in dropped:
                lo.remove(c)

    # چیزهایی که روی سرور اجرا یا خوانده می‌شوند
    props = root.find("properties")
    if props is None:
        props = SubElement(root, "properties")
    for tag in ("Macros", "ExpressionFunctions", "WFSTLayers", "WCSLayers", "WCSUrl", "WFSUrl", "WMSUrl",
                "WMTSUrl"):
        el = props.find(tag)
        if el is not None:
            if tag == "Macros" and _text(el.find("pythonCode")):
                warnings.append("ماکروی پایتون پروژه روی سرور اجرا نمی‌شود و حذف شد.")
            props.remove(el)
    # همه لایه‌های برداری برای WFS (یا هیچ‌کدام)
    vector_ids = [x.id for x in result.layers if x.kind == "vector"]
    _set_list(props, "WFSLayers", vector_ids if wfs else [])
    wfs_prec = props.find("WFSLayersPrecision")
    if wfs_prec is not None:
        props.remove(wfs_prec)
    _set_value(props, "WMSServiceCapabilities", "true", "bool")
    _set_value(props, "WMSServiceTitle", result.title)
    # نام لایه ریشه: LAYERS=all کل نقشه را با همان ترتیب و سبک QGIS می‌کشد
    _set_value(props, "WMSRootName", ROOT_NAME)
    # سیستم‌های مختصات لازم برای نقشه وب
    crs = props.find("WMSCrsList")
    if crs is not None:
        have = [_text(v) for v in crs.findall("value")]
        for code in ("EPSG:3857", "EPSG:4326"):
            if code not in have:
                SubElement(crs, "value").text = code

    xml = tostring(root, encoding="unicode")
    if re.search(r"password\s*=", xml, re.I) or "authcfg=" in xml:
        # رمزی بیرون از منبع داده لایه‌ها (مثلاً در یک چیدمان چاپی) مانده؛ احتیاط
        xml = re.sub(r"password\s*=\s*('(?:[^'\\]|\\.)*'|\S+)", "", xml, flags=re.I)
        xml = re.sub(r"authcfg=\S+", "", xml)
    if not result.layers:
        raise ProjectError("هیچ لایه‌ای از پایگاه داده PostGIS در این پروژه نیست. لایه‌ها را از اتصال "
                           "PostGIS همین پایگاه داده به پروژه اضافه کنید.")
    result.xml = "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n" + xml
    return result


def render(xml: str, conn: str) -> str:
    """نسخه نهایی برای QGIS Server: جای‌نگهدار اتصال با اتصال واقعی نقش فقط‌خواندنی."""
    return xml.replace(PLACEHOLDER, xml_escape(conn, {'"': "&quot;"}))
