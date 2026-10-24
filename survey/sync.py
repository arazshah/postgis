"""
همگام‌سازی داده برداشت با پایگاه داده کاربر؛ مسیر مشترک ثبت زنده، ورود فایل و برنامه آفلاین.

- درج idempotent است: همان client_uuid دوباره بیاید ردیف تازه ساخته نمی‌شود (duplicate).
- هر آیتم جدا پردازش می‌شود؛ خطای یکی بقیه را رد نمی‌کند.
- سقف نقطه پلن (survey_max_points) روی مجموع نقطه‌های همه پروژه‌های فعال پایگاه داده اعمال می‌شود.
"""
import json
import math
import uuid
from datetime import datetime

import psycopg
from psycopg import sql

from databases.explorer import Explorer, ExplorerError

from . import ddl
from .models import SurveyProject

MAX_ITEMS = 1000
KINDS = {"point": "points", "line": "lines", "polygon": "polygons"}
GEOM = {"point": "Point", "line": "LineString", "polygon": "Polygon"}
COMMON = {"code": str, "descr": str, "session_id": "uuid", "captured_at": "ts", "captured_by": str, "device": str,
          "driver_id": str, "driver_version": str, "qc_flags": "texts"}
POINT_ONLY = {"pt_no": str, "pos_source": str, "fix_quality": ("int", 0, 9), "sats": ("int", 0, 200),
              "hdop": ("real", 0, 1000), "pdop": ("real", 0, 1000), "acc_h": ("real", 0, 1e6),
              "std_e": ("real", 0, 1e6), "std_n": ("real", 0, 1e6), "std_h": ("real", 0, 1e6),
              "h_ellip": ("real", -1000, 100000), "h_ortho": ("real", -1000, 100000),
              "antenna_h": ("real", 0, 100), "corr_age": ("real", 0, 1e5)}
TEXT_MAX = 500


class ItemError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _coerce(name, rule, value):
    if value is None:
        return None
    if rule is str:
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ItemError("invalid", f"{name}")
        return str(value)[:TEXT_MAX]
    if rule == "uuid":
        try:
            return str(uuid.UUID(str(value)))
        except ValueError:
            raise ItemError("invalid", name) from None
    if rule == "ts":
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            raise ItemError("invalid", name) from None
    if rule == "texts":
        if not isinstance(value, list) or len(value) > 50:
            raise ItemError("invalid", name)
        return [str(v)[:50] for v in value]
    kind, lo, hi = rule
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ItemError("invalid", name)
    if not lo <= value <= hi:
        raise ItemError("range", name)
    return int(value) if kind == "int" else float(value)


def clean_properties(kind: str, props: dict) -> dict:
    rules = dict(COMMON)
    if kind == "point":
        rules.update(POINT_ONLY)
    out = {}
    for k, v in (props or {}).items():
        if k in rules and v is not None:
            out[k] = _coerce(k, rules[k], v)
    return out


def _coords_ok(c):
    if isinstance(c, (list, tuple)):
        if c and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in c):
            return len(c) >= 2 and all(math.isfinite(x) for x in c[:2])
        return bool(c) and all(_coords_ok(x) for x in c)
    return False


def check_geometry(kind: str, geom) -> None:
    if not isinstance(geom, dict) or geom.get("type") != GEOM[kind] or not _coords_ok(geom.get("coordinates")):
        raise ItemError("geometry", "هندسه با نوع آیتم نمی‌خواند")


def points_used(conn, db) -> int:
    total = 0
    for p in SurveyProject.objects.filter(database=db, archived_at__isnull=True):
        total += conn.execute(sql.SQL("SELECT count(*) FROM {} WHERE deleted_at IS NULL").format(
            sql.Identifier(p.slug, "points"))).fetchone()[0]
    return total


def apply(db, project: SurveyProject, items: list, user_label: str = "") -> list[dict]:
    """آیتم‌ها را در پروژه می‌نویسد و برای هر یک {client_uuid, status, ...} برمی‌گرداند."""
    if not isinstance(items, list):
        raise ItemError("invalid", "items")
    if len(items) > MAX_ITEMS:
        raise ItemError("too_many", f"حداکثر {MAX_ITEMS} آیتم در هر درخواست")
    ddl.check_slug(project.slug)
    results = []
    try:
        with Explorer(db).connect(read_only=False) as conn:
            conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(db.role_name)))
            used = points_used(conn, db)
            cap = db.plan.survey_max_points
            for it in items:
                cu = it.get("client_uuid") if isinstance(it, dict) else None
                try:
                    with conn.transaction():
                        status = _one(conn, project, it, user_label, used, cap)
                    if status == "ok" and isinstance(it, dict) and it.get("kind") == "point" and it.get("op") != "delete":
                        used += 1
                    results.append({"client_uuid": cu, "status": status})
                except ItemError as exc:
                    results.append({"client_uuid": cu, "status": "error", "code": exc.code, "message": str(exc)})
                except psycopg.Error:
                    results.append({"client_uuid": cu, "status": "error", "code": "db"})
            conn.commit()
    except ExplorerError as exc:
        raise ItemError("unavailable", str(exc)) from exc
    return results


def _one(conn, project, it, user_label, used, cap) -> str:
    if not isinstance(it, dict):
        raise ItemError("invalid", "آیتم")
    kind = it.get("kind")
    try:
        cu = str(uuid.UUID(str(it.get("client_uuid"))))
    except ValueError:
        raise ItemError("invalid", "client_uuid") from None
    if kind == "session":
        return _session(conn, project, cu, it, user_label)
    if kind not in KINDS:
        raise ItemError("invalid", "kind")
    table = sql.Identifier(project.slug, KINDS[kind])
    if it.get("op") == "delete":
        row = conn.execute(sql.SQL("UPDATE {} SET deleted_at = now() WHERE client_uuid = %s AND deleted_at IS NULL "
                                   "RETURNING id").format(table), (cu,)).fetchone()
        return "ok" if row else "missing"
    srid = it.get("srid", 4326)
    if srid not in (4326, project.srid):
        raise ItemError("srid", "SRID آیتم باید ۴۳۲۶ یا SRID پروژه باشد")
    geom = it.get("geometry")
    check_geometry(kind, geom)
    props = clean_properties(kind, it.get("properties") or {})
    if user_label and "captured_by" not in props:
        props["captured_by"] = user_label[:TEXT_MAX]
    if kind == "point" and used >= cap:
        raise ItemError("quota", f"سقف {cap} نقطه پلن پر است")
    cols = ["client_uuid", *props.keys(), "geom"]
    geom_sql = sql.SQL("ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), %s), %s)") if srid != project.srid \
        else sql.SQL("ST_SetSRID(ST_GeomFromGeoJSON(%s), %s)")
    geom_args = [json.dumps(geom), srid] + ([project.srid] if srid != project.srid else [])
    values = [sql.SQL("%s")] * (1 + len(props)) + [geom_sql]
    args = [cu, *props.values(), *geom_args]
    stmt = sql.SQL("INSERT INTO {t} ({c}) VALUES ({v}) ON CONFLICT (client_uuid) DO NOTHING RETURNING id").format(
        t=table, c=sql.SQL(", ").join(map(sql.Identifier, cols)), v=sql.SQL(", ").join(values))
    row = conn.execute(stmt, args).fetchone()
    return "ok" if row else "duplicate"


def _session(conn, project, cu, it, user_label) -> str:
    p = it.get("properties") or {}
    row = conn.execute(sql.SQL(
        "INSERT INTO {} (id, name, device, driver_id, created_by, notes) VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET ended_at = CASE WHEN %s THEN now() ELSE {}.ended_at END RETURNING (xmax = 0)"
    ).format(sql.Identifier(project.slug, "sessions"), sql.Identifier(project.slug, "sessions")),
        (cu, _coerce("name", str, p.get("name")), _coerce("device", str, p.get("device")),
         _coerce("driver_id", str, p.get("driver_id")), user_label[:TEXT_MAX] or None,
         _coerce("notes", str, p.get("notes")), bool(p.get("end")))).fetchone()
    return "ok" if row and row[0] else "duplicate"
