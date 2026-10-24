"""
ساخت و آرشیو schema پروژه برداشت در پایگاه داده کاربر.

همه نام‌ها با sql.Identifier ساخته می‌شوند و نام schema پیش از استفاده با الگوی سخت‌گیر بررسی می‌شود.
"""
import re
import secrets

from psycopg import sql

from . import presets

SLUG_RE = re.compile(r"^s_[a-z0-9]{8}$")
_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
TABLES = ("sessions", "points", "lines", "polygons", "control_points", "codes")

_ACCURACY = (
    "pos_source text, fix_quality smallint, sats smallint, hdop real, pdop real, acc_h real, "
    "std_e real, std_n real, std_h real, h_ellip double precision, h_ortho double precision, "
    "antenna_h double precision, corr_age real, ")
_PROVENANCE = (
    "captured_at timestamptz, captured_by text, device text, driver_id text, driver_version text, "
    "qc_flags text[] NOT NULL DEFAULT '{}', synced_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz, ")


def new_slug() -> str:
    return "s_" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


def check_slug(slug: str) -> str:
    if not SLUG_RE.match(slug or ""):
        raise ValueError("نام schema نامعتبر است.")
    return slug


def create_schema(conn, slug: str, srid: int, template: str = "blank") -> None:
    """schema و شش جدول پروژه را می‌سازد. فراخواننده تراکنش و SET ROLE را مدیریت می‌کند."""
    check_slug(slug)
    srid = int(srid)
    ident = lambda name: sql.Identifier(slug, name)  # noqa: E731
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(slug)))
    conn.execute(sql.SQL("""CREATE TABLE {t} (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text, device text, driver_id text,
        started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz, base_info jsonb, notes text,
        created_by text)""").format(t=ident("sessions")))
    for name, gtype in (("points", "Point"), ("lines", "LineString"), ("polygons", "Polygon")):
        is_points = name == "points"
        head = sql.SQL("CREATE TABLE ") + ident(name) + sql.SQL(
            " (id bigserial PRIMARY KEY, client_uuid uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(), "
            "code text, descr text, " + ("pt_no text, " if is_points else "")
            + "session_id uuid REFERENCES ") + ident("sessions") + sql.SQL(
            "(id) ON DELETE SET NULL, " + (_ACCURACY if is_points else "") + _PROVENANCE
            + "geom geometry(" + gtype + ", ") + sql.Literal(srid) + sql.SQL(") NOT NULL)")
        conn.execute(head)
        conn.execute(sql.SQL("CREATE INDEX {i} ON {t} USING gist (geom)").format(
            i=sql.Identifier(f"{name}_geom_gix"), t=ident(name)))
        conn.execute(sql.SQL("CREATE INDEX {i} ON {t} (session_id) WHERE deleted_at IS NULL").format(
            i=sql.Identifier(f"{name}_session_ix"), t=ident(name)))
    conn.execute(sql.SQL("""CREATE TABLE {t} (id serial PRIMARY KEY, pt_no text NOT NULL UNIQUE, descr text,
        h_ortho double precision, acc_h real, geom geometry(Point, {srid}) NOT NULL)""").format(
        t=ident("control_points"), srid=sql.Literal(srid)))
    conn.execute(sql.SQL("CREATE INDEX {i} ON {t} USING gist (geom)").format(
        i=sql.Identifier("control_points_geom_gix"), t=ident("control_points")))
    conn.execute(sql.SQL("""CREATE TABLE {t} (id serial PRIMARY KEY, code text NOT NULL UNIQUE, name text NOT NULL,
        geom_type text NOT NULL CHECK (geom_type IN ('point','line','polygon')), layer text,
        sort smallint NOT NULL DEFAULT 0)""").format(t=ident("codes")))
    rows = presets.TEMPLATES.get(template, presets.TEMPLATES["blank"])[1]
    for i, (code, name, gtype, layer) in enumerate(rows):
        conn.execute(sql.SQL("INSERT INTO {t} (code, name, geom_type, layer, sort) VALUES (%s, %s, %s, %s, %s)").format(
            t=ident("codes")), (code, name, gtype, layer, i))


def drop_schema(conn, slug: str) -> None:
    """فقط برای جبران خطای ساخت پروژه؛ حذف دستی کاربر از Explorer انجام می‌شود."""
    check_slug(slug)
    conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(slug)))
