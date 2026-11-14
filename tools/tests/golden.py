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
    # --- ابزارهای افزوده‌ی جعبه‌ابزار ۵۰تایی ---
    ("ringbuf", False, dict(layer=S, distance="300", rings="3")),
    ("ringbuf", False, dict(layer=S, distance="300", rings="1")),
    ("knn", False, dict(layer=S, other=P, k="3", label="name")),
    ("knn", False, dict(layer=P, other=S, k="30")),
    ("nearlines", False, dict(layer=S, other=P, distance="500")),
    ("nearlines", False, dict(layer=S, other=P, distance="0")),
    ("intersect", False, dict(layer=Z, other=L)),
    ("intersect", False, dict(layer=S, other=L)),
    ("union", False, dict(layer=Z, other=L)),
    ("union", False, dict(layer=Z, other="public.nope")),
    ("symdiff", False, dict(layer=Z, other=L)),
    ("symdiff", False, dict(layer=R, other=L)),
    ("spatialjoin", False, dict(layer=S, other=Z)),
    ("spatialjoin", False, dict(layer=P, other=L, relation="within", keep="on")),
    ("spatialjoin", False, dict(layer=S, other=R)),
    ("centroid", False, dict(layer=Z)),
    ("centroid", False, dict(layer=Z, mode="centroid")),
    ("centroid", False, dict(layer="public.notes")),
    ("hull", False, dict(layer=S)),
    ("hull", False, dict(layer=S, mode="concave", ratio="0.4")),
    ("hull", False, dict(layer=S, mode="concave", ratio="5")),
    ("envelope", False, dict(layer=Z, shape="rotated")),
    ("envelope", False, dict(layer=S, shape="circle", scope="all")),
    ("envelope", False, dict(layer="public.nope")),
    ("dissolve", False, dict(layer=Z, field="landuse")),
    ("dissolve", False, dict(layer=Z)),
    ("dissolve", False, dict(layer=Z, field="nope")),
    ("explode", False, dict(layer=L)),
    ("explode", False, dict(layer="public.nope")),
    ("simplify", False, dict(layer=L, tolerance="50")),
    ("simplify", False, dict(layer=S, tolerance="50")),
    ("simplify", False, dict(layer=L, tolerance="0")),
    ("smooth", False, dict(layer=R, iterations="2")),
    ("smooth", False, dict(layer=R, iterations="9")),
    ("polyline", False, dict(layer=Z)),
    ("polyline", False, dict(layer=R)),
    ("geomstats", False, dict(layer=Z)),
    ("geomstats", False, dict(layer=P)),
    ("geomstats", False, dict(layer="public.plain")),
    ("coords", False, dict(layer=S)),
    ("coords", False, dict(layer="public.nope")),
    ("compact", False, dict(layer=Z)),
    ("compact", False, dict(layer=S)),
    ("bearing", False, dict(layer=R)),
    ("bearing", False, dict(layer=Z)),
    ("linepoints", False, dict(layer=R, distance="100")),
    ("linepoints", False, dict(layer=R, distance="abc")),
    ("linesplit", False, dict(layer=R, distance="500")),
    ("linesplit", False, dict(layer=S, distance="500")),
    ("linecross", False, dict(layer=R)),
    ("linecross", False, dict(layer=R, other=R)),
    ("linecross", False, dict(layer=Z)),
    ("endpoints", False, dict(layer=R)),
    ("endpoints", False, dict(layer=R, which="end")),
    ("endpoints", False, dict(layer=S)),
    ("fishnet", False, dict(layer=S, size="500")),
    ("fishnet", False, dict(layer=P, size="500", empty="on")),
    ("fishnet", False, dict(layer=S, size="1")),
    ("randompts", False, dict(layer=Z, count="10", seed="7")),
    ("randompts", False, dict(layer=Z, count="5000")),
    ("meancenter", False, dict(layer=S)),
    ("meancenter", False, dict(layer=S, weight="price", field="landuse")),
    ("meancenter", False, dict(layer=S, weight="name")),
    ("sdellipse", False, dict(layer=S, k="2")),
    ("sdellipse", False, dict(layer=Z)),
    ("hotspot", False, dict(layer=S, value="price", distance="1000")),
    ("hotspot", False, dict(layer=S, value="name", distance="1000")),
    ("hotspot", False, dict(layer=S, distance="1000")),
    ("kmeans", False, dict(layer=S, k="5")),
    ("kmeans", False, dict(layer=S, k="1")),
    ("makevalid", False, dict(layer=Z)),
    ("makevalid", False, dict(layer=L, only_invalid="on")),
    ("makevalid", False, dict(layer="public.notes")),
    ("dedupe", False, dict(layer=S)),
    ("dedupe", False, dict(layer=S, field="name", tolerance="5")),
    ("dedupe", False, dict(layer=S, tolerance="500")),
    ("snap", False, dict(layer=S, other=R, distance="30")),
    ("snap", False, dict(layer=Z, other=R, distance="30")),
    ("selfoverlap", False, dict(layer=Z, label="name")),
    ("selfoverlap", False, dict(layer=S)),
    ("odmatrix", True, dict(layer=S, other=P, distance="5000")),
    ("odmatrix", False, dict(layer=S, other=P, distance="5000")),
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
        with mock.patch("kernel.tenantdb.catalog", return_value=ex):
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
