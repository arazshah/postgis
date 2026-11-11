"""موارد «SQL طلایی»: برای هر ابزار چند ورودی ثابت که خروجی‌شان (SELECT، سقف‌ها، خلاصه یا پیام خطا) نباید با بازسازی عوض شود.

بازتولید فایل (فقط وقتی تغییر SQL عمدی است): python -m tools.tests.golden
"""
import json
from pathlib import Path
from unittest import mock

from databases.explorer import TableRef

PATH = Path(__file__).with_name("golden_sql.json")


def _t(name, gtype, schema="public", srid=4326, col="geom"):
    return TableRef(schema, name, 1, "r", geometry=[{"column": col, "type": gtype, "srid": srid, "geography": False}])


LAYERS = [_t("schools", "POINT"), _t("roads", "LINESTRING"), _t("zones", "POLYGON"), _t("landuse", "MULTIPOLYGON", srid=32639),
          _t("pois", "POINT", srid=32639, col="shape"), _t("mixed", "GEOMETRY", srid=0), _t("plain", "", srid=0),
          TableRef("public", "notes", 1, "r", geometry=[])]
ROUTING = [_t("ways", "LINESTRING", schema="routing", col="the_geom"),
           _t("ways_vertices_pgr", "POINT", schema="routing", col="the_geom")]
BASE = [{"name": "gid", "spatial": False, "base": "int4"}, {"name": "name", "spatial": False, "base": "text"},
        {"name": "price", "spatial": False, "base": "float8"}, {"name": "landuse", "spatial": False, "base": "text"}]


def _columns(t):
    geom = t.geometry[0]["column"] if t.geometry else None
    return BASE + ([{"name": geom, "spatial": True, "base": "geometry"}] if geom else [])


S, R, Z, L, P = "public.schools", "public.roads", "public.zones", "public.landuse", "public.pois"
CASES = [
    # (ابزار، شبکه‌ی معابر هست؟، پارامترها)
    ("buffer", False, dict(layer=S, distance="500")),
    ("buffer", False, dict(layer=L, distance="۱٬۲۰۰".replace("٬", ","), dissolve="on")),
    ("buffer", False, dict(layer="public.mixed", distance="50")),
    ("buffer", False, dict(layer=S, distance="0")),
    ("buffer", False, dict(layer=S, distance="abc")),
    ("buffer", False, dict(layer="public.notes", distance="10")),
    ("buffer", False, dict(layer="public.nope", distance="10")),
    ("buffer", False, dict(layer=S, distance="10", output="Bad Name")),
    ("buffer", False, dict(layer=S, distance="10", output="schools")),
    ("buffer", False, dict(layer=S, distance="10", output="schools", replace="on")),
    ("nearest", False, dict(layer=S, other=Z)),
    ("nearest", False, dict(layer=S, other=P, label="name")),
    ("nearest", False, dict(layer=P, other=L, label="landuse")),
    ("nearest", False, dict(layer=S, other=Z, label="nope")),
    ("count", False, dict(layer=Z, other=S)),
    ("count", False, dict(layer=L, other=P, value="price", agg="avg")),
    ("count", False, dict(layer=Z, other=S, value="price")),
    ("count", False, dict(layer=Z, other=S, value="name")),
    ("count", False, dict(layer=S, other=S)),
    ("overlap", False, dict(layer=Z, other=L, zone="name", category="landuse")),
    ("overlap", False, dict(layer=Z, other=L, zone="name", category="nope")),
    ("overlap", False, dict(layer=Z, other=L, zone="", category="landuse")),
    ("change", False, dict(layer=L, other=Z, category="landuse", category2="name")),
    ("change", False, dict(layer=L, other=Z, category="landuse", category2="")),
    ("hexbin", False, dict(layer=S, size="500")),
    ("hexbin", False, dict(layer=P, size="19")),
    ("isochrone", True, dict(lon="51.389", lat="35.7", distance="1000")),
    ("isochrone", False, dict(lon="51.389", lat="35.7", distance="1000")),
    ("isochrone", True, dict(lon="200", lat="35.7", distance="1000")),
    ("within", False, dict(layer=S, other=R, distance="300")),
    ("within", False, dict(layer=S, other=L, distance="300")),
    ("voronoi", False, dict(layer=S)),
    ("voronoi", False, dict(layer=P, other=L)),
    ("voronoi", False, dict(layer=Z)),
    ("cluster", False, dict(layer=S, distance="200", minpoints="5")),
    ("cluster", False, dict(layer=S, distance="200", minpoints="1")),
    ("measure", False, dict(layer=Z, other=R, mode="length")),
    ("measure", False, dict(layer=Z, other=L, mode="area")),
    ("measure", False, dict(layer=Z, other=S)),
    ("clip", False, dict(layer=R, other=Z)),
    ("clip", False, dict(layer=P, other=L)),
    ("clip", False, dict(layer="public.mixed", other=Z)),
    ("erase", False, dict(layer=Z, other=L)),
    ("erase", False, dict(layer=R, other=Z)),
    ("route", True, dict(lon="51.3", lat="35.7", lon2="51.4", lat2="35.8")),
    ("route", False, dict(lon="51.3", lat="35.7", lon2="51.4", lat2="35.8")),
    ("netnearest", True, dict(layer=S, other=P, label="name", distance="5000")),
    ("netnearest", True, dict(layer=S, other=S, distance="5000")),
    ("netnearest", True, dict(layer=Z, other=S, distance="5000")),
    ("coverage", True, dict(layer=S, distance="800")),
    ("coverage", False, dict(layer=S, distance="800")),
    ("nope", False, dict(layer=S)),
]


def _text(x):
    return x.as_string(None) if hasattr(x, "as_string") else str(x)


def render(engine, key, routing, params):
    """خروجی پایدار یک مورد با موتور فعلی (Explorer ساختگی؛ بدون PostgreSQL)."""
    ex = mock.MagicMock()
    ex.tables.return_value = LAYERS + (ROUTING if routing else [])
    ex.columns.side_effect = _columns
    # ستون با نوع عمومی (GEOMETRY): نوع واقعی از چند ردیف اول خوانده می‌شود
    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = [("POINT",), ("LINESTRING",)]
    ex.connect.return_value.__enter__.return_value = conn
    p = {"output": "out_t", **params}
    try:
        with mock.patch.object(engine, "Explorer", return_value=ex):
            _ex, out, target, body, guards = engine._prepare(None, key, p)
            summary = engine.summarize(None, key, p)
    except engine.ToolError as exc:
        return {"error": str(exc)}
    return {"out": out, "target": _text(target), "sql": _text(body),
            "guards": [[_text(q), cap, msg] for q, cap, msg in guards], "summary": summary}


def build(engine):
    return [{"tool": k, "routing": r, "params": p, "result": render(engine, k, r, p)} for k, r, p in CASES]


if __name__ == "__main__":
    import django

    django.setup()
    from tools import engine

    PATH.write_text(json.dumps(build(engine), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(CASES)} مورد در {PATH.name} نوشته شد.")
