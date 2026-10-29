"""
داده آماده ایران از OpenStreetMap (مجوز ODbL 1.0، با ذکر منبع).

روی سرور: worker هر هفته فایل ایران را از Geofabrik می‌گیرد (OSM_SOURCE_URL)، مرز استان‌ها، شهرستان‌ها و
شهرها را از خود فایل درمی‌آورد (جدول Area) و هر درخواست کاربر را این‌طور انجام می‌دهد:

  osmium extract (با چندضلعی مرز ناحیه) → ogr2ogr برای هر دسته داده → جدول‌های osm_* در پایگاه داده کاربر
  و در صورت درخواست: osmium cat → osm2pgrouting → شبکه مسیریابی pgRouting در schema «routing»

هیچ‌کدام از این ابزارها با کاربر مدیر به پایگاه داده کاربر وصل نمی‌شوند (همان نقش مرورگر و role کاربر).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from psycopg import sql

from databases import gdal

log = logging.getLogger(__name__)

ATTRIBUTION = "© مشارکت‌کنندگان OpenStreetMap — مجوز ODbL 1.0 — https://www.openstreetmap.org/copyright"
OSMCONF = Path(__file__).parent / "osmconf.ini"
# در OSM ایران: استان ۴، شهرستان ۶ (در برخی داده‌ها ۵)، بخش ۷، و شهر ۸؛ دهستان‌های روستایی را کنار می‌گذاریم.
LEVELS = {"4": "province", "5": "county", "6": "county", "8": "city"}
_RURAL_PLACES = {"village", "hamlet", "locality", "farm", "isolated_dwelling"}
ROUTING_MAX_MB = int(os.environ.get("OSM_ROUTING_MAX_MB", "40"))


class OsmError(Exception):
    pass


@dataclass(frozen=True)
class Dataset:
    key: str
    title: str
    description: str
    layer: str  # لایه درایور OSM در GDAL
    where: str
    columns: tuple[str, ...]


# ستون‌ها: (عبارت OGR SQL، نام ستون خروجی)
# درایور OSM در GDAL «:» نام برچسب‌ها را به «_» تبدیل می‌کند (name:fa ← name_fa)
_NAME = ("COALESCE(name_fa, name) AS name", "name_en")
DATASETS = [
    Dataset("roads", "معابر و جاده‌ها", "بزرگراه تا کوچه، با نوع، یک‌طرفه، سرعت مجاز و تعداد خط", "lines",
            "highway IS NOT NULL",
            (*_NAME, "highway", "oneway", "maxspeed", "lanes", "surface", "bridge", "tunnel")),
    Dataset("pois", "مکان‌های مهم", "مدرسه، بیمارستان، داروخانه، بانک، رستوران، مسجد، فروشگاه و …", "points",
            "amenity IS NOT NULL OR shop IS NOT NULL OR tourism IS NOT NULL OR healthcare IS NOT NULL "
            "OR leisure IS NOT NULL OR office IS NOT NULL OR historic IS NOT NULL",
            (*_NAME, "amenity", "shop", "tourism", "healthcare", "leisure", "office", "historic", "religion",
             "addr_street AS street", "phone", "website", "opening_hours")),
    Dataset("buildings", "ساختمان‌ها", "چندضلعی ساختمان‌ها با نوع و تعداد طبقه (اگر ثبت شده باشد)",
            "multipolygons", "building IS NOT NULL",
            (*_NAME, "building", "building_levels AS levels", "amenity")),
    Dataset("landuse", "کاربری زمین و فضای سبز", "پارک، باغ، کشاورزی، مسکونی، صنعتی، جنگل و …",
            "multipolygons", "(landuse IS NOT NULL OR leisure IS NOT NULL OR \"natural\" IS NOT NULL) "
            "AND building IS NULL", (*_NAME, "landuse", "leisure", '"natural" AS nature')),
    Dataset("water", "رودها و آب", "رود، نهر و کانال (خطی)", "lines", "waterway IS NOT NULL",
            (*_NAME, "waterway")),
    Dataset("railways", "راه‌آهن و مترو", "خطوط راه‌آهن، مترو و قطار شهری", "lines", "railway IS NOT NULL",
            (*_NAME, "railway")),
    Dataset("places", "شهرها و محله‌ها (نقطه)", "نام شهر، روستا و محله با جمعیت", "points", "place IS NOT NULL",
            (*_NAME, "place", "population")),
    Dataset("boundaries", "مرزهای اداری", "استان، شهرستان، بخش و شهر", "multipolygons",
            "boundary = 'administrative'", (*_NAME, "admin_level")),
]
DATASET_MAP = {d.key: d for d in DATASETS}


# ---------------------------------------------------------------------- فایل‌ها
def root() -> Path:
    p = Path(settings.OSM_ROOT)
    p.mkdir(parents=True, exist_ok=True)
    return p


def source_file() -> Path:
    return root() / "iran-latest.osm.pbf"


def source_info() -> dict | None:
    f = source_file()
    if not f.exists():
        return None
    st = f.stat()
    return {"size": st.st_size, "updated": timezone.datetime.fromtimestamp(st.st_mtime, tz=timezone.get_current_timezone())}


def _bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise OsmError(f"{name} روی سرور نصب نیست.")
    return path


def _run(cmd: list[str], env: dict | None = None, timeout: int = 3600) -> str:
    try:
        proc = subprocess.run(cmd, env=env or os.environ.copy(), capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise OsmError(f"{Path(cmd[0]).name} بیش از حد طول کشید.") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip().replace(os.environ.get("PGPASSWORD", "\0"), "***")
        raise OsmError(f"{Path(cmd[0]).name} ناموفق بود: {err[-800:]}")
    return proc.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------------- دانلود و نواحی
def download_source(url: str | None = None) -> Path:
    """فایل ایران را (با فایل موقت و جایگزینی اتمی) می‌گیرد و نواحی را دوباره می‌سازد."""
    url = url or settings.OSM_SOURCE_URL
    dest = source_file()
    # osmium نوع فایل را از پسوند می‌شناسد؛ پسوند موقت باید باز هم .osm.pbf باشد
    tmp = dest.with_name("iran-latest.part.osm.pbf")
    req = urllib.request.Request(url, headers={"User-Agent": "postgis.ir osm refresh"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:  # noqa: S310 آدرس از تنظیمات
        shutil.copyfileobj(r, f, length=1024 * 1024)
    if tmp.stat().st_size < 1024:
        tmp.unlink()
        raise OsmError("فایل دانلودشده خالی است.")
    _run([_bin("osmium"), "fileinfo", "-F", "pbf", str(tmp)], timeout=600)  # فایل سالم است؟
    tmp.replace(dest)
    refresh_areas()
    return dest


def refresh_areas() -> int:
    """مرز استان (۴)، شهرستان (۶ یا ۵) و شهر (۸) از خود فایل؛ چندضلعی ساده‌شده برای برش با osmium."""
    from .models import Area

    src = source_file()
    if not src.exists():
        raise OsmError("فایل OSM ایران هنوز دانلود نشده است.")
    with tempfile.TemporaryDirectory() as d:
        bnd = Path(d) / "boundaries.osm.pbf"
        _run([_bin("osmium"), "tags-filter", "--overwrite", "-o", str(bnd), str(src),
              "r/boundary=administrative"])
        out = Path(d) / "areas.geojsonl"
        gdal._run([gdal._bin("ogr2ogr"), "-f", "GeoJSONSeq", str(out), str(bnd), "multipolygons",
                   "-where", "admin_level IN ('4','5','6','8')", "-simplify", "0.002",
                   "-oo", f"CONFIG_FILE={OSMCONF}", "-lco", "RS=NO"], env=gdal._env())
        rows = []
        for line in out.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            f = json.loads(line)
            p = f.get("properties") or {}
            name = p.get("name_fa") or p.get("name")
            geom = f.get("geometry")
            if not name or not geom:
                continue
            if p.get("admin_level") == "8" and (p.get("place") or "") in _RURAL_PLACES:
                continue
            xs, ys = _coords(geom)
            rows.append(Area(name=name[:120], name_en=(p.get("name_en") or "")[:120], level=LEVELS[p["admin_level"]],
                             osm_id=str(p.get("osm_id") or ""), population=_int(p.get("population")),
                             bbox=[min(xs), min(ys), max(xs), max(ys)], geometry=geom))
    if not rows:
        raise OsmError("هیچ مرز اداری در فایل OSM پیدا نشد.")
    Area.objects.all().delete()
    Area.objects.bulk_create(rows)
    _assign_parents()
    return len(rows)


def _int(v) -> int | None:
    try:
        return int(str(v).replace(",", "").split(".")[0])
    except (TypeError, ValueError):
        return None


def _coords(geom: dict) -> tuple[list[float], list[float]]:
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for x in c:
                walk(x)

    walk(geom["coordinates"])
    return xs, ys


def _assign_parents():
    """استان هر شهرستان و شهر: کوچک‌ترین ناحیه سطح بالاتر که مرکز جعبه را دارد."""
    from .models import Area

    provinces = list(Area.objects.filter(level="province"))
    counties = list(Area.objects.filter(level="county"))

    def find(a, candidates):
        cx, cy = (a.bbox[0] + a.bbox[2]) / 2, (a.bbox[1] + a.bbox[3]) / 2
        hits = [c for c in candidates if c.bbox[0] <= cx <= c.bbox[2] and c.bbox[1] <= cy <= c.bbox[3]]
        return min(hits, key=lambda c: (c.bbox[2] - c.bbox[0]) * (c.bbox[3] - c.bbox[1])) if hits else None

    for a in counties + list(Area.objects.filter(level="city")):
        p = find(a, provinces)
        if p:
            a.province = p.name
            a.save(update_fields=["province"])


# ---------------------------------------------------------------------- برش و ورود
def extract(area, dest: Path) -> Path:
    src = source_file()
    if not src.exists():
        raise OsmError("داده OSM ایران هنوز روی سرور آماده نیست؛ مدیر سایت باید آن را به‌روز کند.")
    poly = dest.with_suffix(".geojson")
    poly.write_text(json.dumps({"type": "Feature", "properties": {}, "geometry": area.geometry}), encoding="utf-8")
    _run([_bin("osmium"), "extract", "--overwrite", "-s", "smart", "-p", str(poly), "-o", str(dest), str(src)])
    return dest


def import_dataset(db, pbf: Path, ds: Dataset, table_prefix: str = "osm_") -> int:
    table = f"{table_prefix}{ds.key}"
    tgt = gdal.target(db)
    cols = ", ".join(ds.columns + ("osm_id", "geometry"))  # در گویش SQLite هندسه باید صریح انتخاب شود
    query = f"SELECT {cols} FROM {ds.layer} WHERE {ds.where}"
    gdal._run([gdal._bin("ogr2ogr"), "-f", "PostgreSQL", tgt.conn, str(pbf), "-sql", query, "-dialect", "SQLite",
               "-oo", f"CONFIG_FILE={OSMCONF}", "-nln", f"public.{table}", "-overwrite",
               "-lco", "GEOMETRY_NAME=geom", "-lco", "FID=gid", "-lco", "SPATIAL_INDEX=GIST",
               "-lco", "LAUNDER=YES", "-lco", "PRECISION=NO", "-nlt",
               "PROMOTE_TO_MULTI", "-gt", "50000", "--config", "OSM_USE_CUSTOM_INDEXING", "NO"], env=tgt.env)
    from databases.explorer import Explorer

    with Explorer(db).connect(read_only=False) as conn:
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(db.role_name)))
        conn.execute(sql.SQL("COMMENT ON TABLE {} IS {}").format(
            sql.Identifier("public", table), sql.Literal(f"{ds.title} — {ATTRIBUTION}")))
        n = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("public", table))).fetchone()[0]
        conn.commit()
    return n


def import_routing(db, pbf: Path) -> int:
    """شبکه مسیریابی با osm2pgrouting در schema routing (جدول ways با cost و reverse_cost)."""
    from databases.explorer import Explorer
    from databases.provisioner import Provisioner

    if pbf.stat().st_size > ROUTING_MAX_MB * 1024 * 1024:
        raise OsmError(f"ناحیه برای شبکه مسیریابی بزرگ است (بیش از {ROUTING_MAX_MB} مگابایت داده OSM)؛ "
                       "یک شهر یا شهرستان انتخاب کنید.")
    Provisioner.for_server(db.server).install_extension(db.db_name, "pgrouting")
    with Explorer(db).connect(read_only=False) as conn:
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(db.role_name)))
        conn.execute("CREATE SCHEMA IF NOT EXISTS routing")
        conn.commit()
    tgt = gdal.target(db)
    with tempfile.TemporaryDirectory() as d:
        osm = Path(d) / "area.osm"
        _run([_bin("osmium"), "cat", "--overwrite", "-o", str(osm), str(pbf)])
        conf = _mapconfig()
        server = db.server
        user = Provisioner.browser_role_name(db.role_name)
        # osm2pgrouting رمز خالی می‌فرستد و PGPASSWORD را نادیده می‌گیرد؛ libpq در آن حالت فایل رمز را می‌خواند.
        # رمز در فایل موقت با دسترسی ۶۰۰ است، نه در خط فرمان (که در فهرست پروسه‌ها دیده می‌شود).
        pgpass = Path(d) / "pgpass"
        esc = lambda v: str(v).replace("\\", "\\\\").replace(":", "\\:")  # noqa: E731
        pgpass.write_text(f"{esc(server.host)}:{server.port}:{esc(db.db_name)}:{esc(user)}:{esc(tgt.env['PGPASSWORD'])}\n")
        pgpass.chmod(0o600)
        env = {**tgt.env, "PGSSLMODE": server.sslmode, "PGPASSFILE": str(pgpass)}
        env.pop("PGPASSWORD", None)
        _run([_bin("osm2pgrouting"), "--f", str(osm), "--conf", conf, "--dbname", db.db_name,
              "--username", user, "--host", server.host, "--port", str(server.port), "--schema", "routing",
              "--clean", "--chunk", "20000"], env=env, timeout=3600)
    with Explorer(db).connect(read_only=False) as conn:
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(db.role_name)))
        for t in ("ways", "ways_vertices_pgr"):
            conn.execute(sql.SQL("COMMENT ON TABLE {} IS {}").format(
                sql.Identifier("routing", t), sql.Literal(f"شبکه مسیریابی — {ATTRIBUTION}")))
        n = conn.execute("SELECT count(*) FROM routing.ways").fetchone()[0]
        conn.commit()
    return n


def _mapconfig() -> str:
    for p in ("/usr/share/osm2pgrouting/mapconfig.xml", "/usr/local/share/osm2pgrouting/mapconfig.xml"):
        if Path(p).exists():
            return p
    raise OsmError("فایل mapconfig برنامه osm2pgrouting پیدا نشد.")
