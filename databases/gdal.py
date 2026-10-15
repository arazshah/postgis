"""
ورود و خروج فایل‌های مکانی با GDAL (ogr2ogr / ogrinfo).

- ورود: Shapefile (zip)، GeoPackage، GeoJSON، KML/KMZ، CSV با ستون مختصات یا WKT، DXF، GML.
  فایل از طریق vsizip خوانده می‌شود (هیچ چیزی از zip روی دیسک باز نمی‌شود).
- انکودینگ Shapefile بدون فایل cpg خودکار حدس زده می‌شود (UTF-8 یا CP1256 ویندوز فارسی).
- اتصال به پایگاه داده کاربر با نقش مرورگر و «role» خود کاربر انجام می‌شود تا جدول‌ها مال کاربر باشند.
- GDAL اجازه دسترسی به شبکه ندارد (لینک‌های شبکه KML و ... باز نمی‌شوند).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .provisioner import Provisioner

ALLOWED_EXT = {".zip", ".gpkg", ".geojson", ".json", ".kml", ".kmz", ".csv", ".dxf", ".gml"}
EXPORT_FORMATS = {
    # کلید: (درایور، پسوند، برچسب)
    "gpkg": ("GPKG", "gpkg", "GeoPackage"),
    "shp": ("ESRI Shapefile", "zip", "Shapefile"),
    "kml": ("KML", "kml", "KML (گوگل ارث)"),
    "dxf": ("DXF", "dxf", "DXF (اتوکد)"),
    "xlsx": ("XLSX", "xlsx", "اکسل"),
}
TABLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
SRID_CHOICES = [
    (4326, "WGS 84 جغرافیایی (طول و عرض)"),
    (32638, "UTM زون 38 شمالی"), (32639, "UTM زون 39 شمالی"), (32640, "UTM زون 40 شمالی"),
    (32641, "UTM زون 41 شمالی"), (3857, "Web Mercator"),
    (23038, "ED50 UTM زون 38"), (23039, "ED50 UTM زون 39"), (23040, "ED50 UTM زون 40"), (23041, "ED50 UTM زون 41"),
]
CSV_X = "lon,lng,long,longitude,x,طول,طول_جغرافیایی"
CSV_Y = "lat,latitude,y,عرض,عرض_جغرافیایی"
CSV_GEOM = "wkt,geom,geometry,the_geom"
TIMEOUT = 3600


class GdalError(Exception):
    pass


def _env(extra: dict | None = None) -> dict:
    env = {**os.environ,
           # بدون شبکه: هر درخواست HTTP داخل GDAL به یک پراکسی ناموجود می‌رود و فوراً شکست می‌خورد
           "GDAL_HTTP_PROXY": "127.0.0.1:9", "GDAL_HTTP_TIMEOUT": "1", "GDAL_HTTP_MAX_RETRY": "0",
           "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".none", "CPL_DEBUG": "OFF"}
    env.update(extra or {})
    return env


def _bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise GdalError(f"{name} روی سرور نصب نیست (بسته gdal-bin).")
    return path


def _run(cmd: list[str], env: dict | None = None, timeout: int = TIMEOUT) -> str:
    try:
        proc = subprocess.run(cmd, env=env or _env(), capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise GdalError("پردازش فایل بیش از حد طول کشید.") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        err = re.sub(r"password=\S+", "password=***", err)
        raise GdalError(err.splitlines()[-1] if err else f"{Path(cmd[0]).name} ناموفق بود.")
    return proc.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------------- بررسی فایل ورودی
def source_path(path: Path) -> str:
    return f"/vsizip/{path}" if path.suffix.lower() == ".zip" else str(path)


def guess_encoding(path: Path) -> str | None:
    """برای Shapefile: اگر cpg دارد None (GDAL خودش می‌خواند)، وگرنه UTF-8 یا CP1256 از روی بایت‌های dbf."""
    if path.suffix.lower() != ".zip":
        return None
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if any(n.lower().endswith(".cpg") for n in names):
                return None
            dbfs = [n for n in names if n.lower().endswith(".dbf")]
            if not dbfs:
                return None
            data = z.read(dbfs[0])[:400_000]
    except (zipfile.BadZipFile, OSError) as exc:
        raise GdalError("فایل zip خراب است یا باز نمی‌شود.") from exc
    try:
        data.decode("utf-8")
        return "UTF-8"
    except UnicodeDecodeError:
        return "CP1256"


def _open_options(path: Path, encoding: str | None) -> list[str]:
    opts = []
    if encoding:
        opts += ["-oo", f"ENCODING={encoding}"]
    if path.suffix.lower() == ".csv":
        opts += ["-oo", f"X_POSSIBLE_NAMES={CSV_X}", "-oo", f"Y_POSSIBLE_NAMES={CSV_Y}",
                 "-oo", f"GEOM_POSSIBLE_NAMES={CSV_GEOM}", "-oo", "KEEP_GEOM_COLUMNS=NO",
                 "-oo", "AUTODETECT_TYPE=YES"]
    return opts


def _srid(geom_field: dict) -> int | None:
    cs = geom_field.get("coordinateSystem") or {}
    ident = (cs.get("projjson") or {}).get("id") or {}
    if ident.get("authority") == "EPSG":
        try:
            return int(ident.get("code"))
        except (TypeError, ValueError):
            return None
    return None


def default_table_name(layer: str) -> str:
    name = re.sub(r"[^a-z0-9_]+", "_", layer.lower()).strip("_")
    if not name or not re.match(r"[a-z_]", name):
        name = f"layer_{name}" if name else "layer"
    return name[:60]


def inspect(path: Path) -> dict:
    """لایه‌ها، تعداد عارضه، نوع هندسه، SRID، ستون‌ها و چند سطر نمونه (با انکودینگ حدس‌زده)."""
    encoding = guess_encoding(path)
    src = source_path(path)
    out = _run([_bin("ogrinfo"), "-json", "-ro", "-so", "-al", *_open_options(path, encoding), src], timeout=60)
    try:
        info = json.loads(out)
    except json.JSONDecodeError as exc:
        raise GdalError("فایل خوانده نشد؛ قالب آن پشتیبانی نمی‌شود یا خراب است.") from exc
    layers = []
    for lyr in info.get("layers", []):
        gfs = lyr.get("geometryFields") or []
        layers.append({
            "name": lyr["name"],
            "count": lyr.get("featureCount", -1),
            "geom_type": gfs[0].get("type", "") if gfs else "",
            "srid": _srid(gfs[0]) if gfs else None,
            "fields": [f["name"] for f in lyr.get("fields", [])][:40],
            "table": default_table_name(lyr["name"]),
        })
    if not layers:
        raise GdalError("هیچ لایه‌ای در فایل پیدا نشد. Shapefile را همراه فایل‌های dbf، shx و prj در یک zip بگذارید.")
    for lyr in layers[:10]:
        lyr["sample"] = sample(path, lyr["name"], encoding)
    return {"driver": info.get("driverShortName", ""), "encoding": encoding, "layers": layers}


def sample(path: Path, layer: str, encoding: str | None, n: int = 3) -> list[dict]:
    try:
        out = _run([_bin("ogr2ogr"), "-f", "GeoJSON", "/vsistdout/", *_open_options(path, encoding),
                    source_path(path), layer, "-limit", str(n), "-lco", "RFC7946=NO"], timeout=60)
        return [f.get("properties") or {} for f in json.loads(out).get("features", [])]
    except (GdalError, json.JSONDecodeError):
        return []


# ---------------------------------------------------------------------- اتصال به پایگاه داده کاربر
@dataclass
class Target:
    conn: str
    env: dict


def target(db, timeout_s: int = 0) -> Target:
    """رشته اتصال PG برای ogr2ogr با نقش مرورگر؛ role و timeout با PGOPTIONS (رمز در محیط، نه در دستور)."""
    from .explorer import Explorer

    ex = Explorer(db)
    password = ex._ensure_role()
    server = db.server
    conn = (f"PG:host={server.host} port={server.port} dbname={db.db_name} "
            f"user={Provisioner.browser_role_name(db.role_name)} sslmode={server.sslmode} "
            f"application_name=geopaygah-gdal")
    env = _env({"PGPASSWORD": password,
                "PGOPTIONS": f"-c role={db.role_name} -c statement_timeout={int(timeout_s * 1000)}",
                "PG_USE_COPY": "YES"})
    return Target(conn, env)


def import_layer(db, path: Path, layer: dict, encoding: str | None) -> None:
    """layer: {name, table, srid, assign_srid, to4326, mode(create|overwrite|append), geom_type}"""
    table = layer["table"]
    if not TABLE_RE.match(table):
        raise GdalError(f"نام جدول «{table}» نامعتبر است.")
    tgt = target(db)
    cmd = [_bin("ogr2ogr"), "-f", "PostgreSQL", tgt.conn, *_open_options(path, encoding), source_path(path),
           layer["name"], "-nln", f"public.{table}", "-gt", "20000"]
    gtype = (layer.get("geom_type") or "").lower()
    if layer.get("mode") != "append":
        cmd += ["-lco", "GEOMETRY_NAME=geom", "-lco", "FID=gid", "-lco", "SPATIAL_INDEX=GIST",
                "-lco", "LAUNDER=YES", "-lco", "PRECISION=NO"]
        mixed = gtype in ("", "unknown", "geometry", "geometrycollection") or "collection" in gtype
        cmd += ["-nlt", "GEOMETRY" if mixed else "PROMOTE_TO_MULTI"]
    if layer.get("mode") == "overwrite":
        cmd += ["-overwrite"]
    elif layer.get("mode") == "append":
        cmd += ["-append"]
    if layer.get("srid") and layer.get("assign_srid"):
        cmd += ["-a_srs", f"EPSG:{int(layer['srid'])}"]
    if layer.get("to4326"):
        cmd += ["-t_srs", "EPSG:4326"]
    if path.suffix.lower() == ".csv" and not layer.get("srid"):
        cmd += ["-a_srs", "EPSG:4326"]
    _run(cmd, env=tgt.env)


# ---------------------------------------------------------------------- خروجی
def export_table(db, schema: str, table: str, fmt: str, workdir: Path, geom_col: str | None = None) -> Path:
    if fmt not in EXPORT_FORMATS:
        raise GdalError("قالب خروجی نامعتبر است.")
    driver, ext, _label = EXPORT_FORMATS[fmt]
    tgt = target(db, timeout_s=110)
    out = workdir / (f"{table}.{ext}" if fmt != "shp" else table)
    cmd = [_bin("ogr2ogr"), "-f", driver, str(out), tgt.conn]
    if fmt == "xlsx":
        # اکسل هندسه ندارد؛ ستون wkt جای آن می‌نشیند (نام‌ها از کاتالوگ آمده‌اند و نقل‌قول می‌شوند)
        wkt = f', ST_AsText("{geom_col}") AS wkt' if geom_col else ""
        cmd += ["-sql", f'SELECT *{wkt} FROM "{schema}"."{table}"', "-nln", table[:31]]
    else:
        cmd += [f"{schema}.{table}", "-nln", table]
    if fmt == "shp":
        cmd += ["-lco", "ENCODING=UTF-8"]
    if fmt == "kml":
        cmd += ["-t_srs", "EPSG:4326"]
    _run(cmd, env=tgt.env, timeout=115)
    if fmt == "shp":
        zpath = workdir / f"{table}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(out.iterdir() if out.is_dir() else out.parent.glob(f"{table}.*")):
                if f.suffix != ".zip":
                    z.write(f, f.name)
        return zpath
    return out


def new_workdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="gp-gdal-"))

