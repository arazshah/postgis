"""
PMTiles ساختگی با طرح Protomaps از فایل OSM ساختگی (برای آزمون و ضبط ویدیو؛ روی سرور فایل واقعی ساخته می‌شود).
python fake_basemap.py sample.osm.pbf out.pmtiles
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

src, dest = sys.argv[1], sys.argv[2]
ROAD = {"motorway": ("highway", 6), "trunk": ("highway", 7), "primary": ("major_road", 9),
        "secondary": ("major_road", 11), "tertiary": ("medium_road", 12), "residential": ("minor_road", 13),
        "service": ("minor_road", 14), "footway": ("path", 14)}


def layer(d, name, sql):
    out = Path(d) / f"{name}.geojson"
    subprocess.run(["ogr2ogr", "-f", "GeoJSON", str(out), src, "-sql", sql, "-oo", "CONFIG_FILE=" + str(Path(__file__).resolve().parents[1] / "osmconf.ini"), "-dialect", "SQLite"], check=True,
                   capture_output=True)
    return json.loads(out.read_text())["features"]


with tempfile.TemporaryDirectory() as d:
    layers = {k: [] for k in ("earth", "water", "landuse", "roads", "buildings", "places", "pois", "boundaries")}
    xs = [51.0, 51.8]
    ys = [35.4, 36.0]
    layers["earth"].append({"type": "Feature", "properties": {"kind": "earth"}, "geometry": {
        "type": "Polygon", "coordinates": [[[xs[0], ys[0]], [xs[1], ys[0]], [xs[1], ys[1]], [xs[0], ys[1]], [xs[0], ys[0]]]]}})
    for f in layer(d, "lines", "SELECT name, highway, waterway, railway, geometry FROM lines"):
        p = f["properties"]
        if p.get("highway") in ROAD:
            kind, mz = ROAD[p["highway"]]
            f["properties"] = {"kind": kind, "kind_detail": p["highway"], "name": p.get("name"),
                               "name:fa": p.get("name"), "min_zoom": mz}
            layers["roads"].append(f)
        elif p.get("waterway"):
            f["properties"] = {"kind": "river", "name": p.get("name"), "min_zoom": 9}
            layers["water"].append(f)
        elif p.get("railway"):
            f["properties"] = {"kind": "rail", "kind_detail": p["railway"], "min_zoom": 11}
            layers["roads"].append(f)
    for f in layer(d, "polys", "SELECT name, building, landuse, leisure, \"natural\" AS nat, boundary, admin_level, "
                   "geometry FROM multipolygons"):
        p = f["properties"]
        if p.get("building"):
            f["properties"] = {"kind": "building", "min_zoom": 14}
            layers["buildings"].append(f)
        elif p.get("boundary") == "administrative":
            continue
        elif p.get("leisure") == "park" or p.get("landuse") in ("grass", "forest"):
            f["properties"] = {"kind": "park" if p.get("leisure") else p["landuse"], "name": p.get("name"),
                               "min_zoom": 10}
            layers["landuse"].append(f)
        elif p.get("nat") == "water":
            f["properties"] = {"kind": "lake", "name": p.get("name"), "min_zoom": 9}
            layers["water"].append(f)
        elif p.get("landuse"):
            f["properties"] = {"kind": p["landuse"], "min_zoom": 11}
            layers["landuse"].append(f)
    for f in layer(d, "points", "SELECT name, place, amenity, population, geometry FROM points"):
        p = f["properties"]
        if p.get("place"):
            city = p["place"] == "city"
            f["properties"] = {"kind": "locality" if city else "neighbourhood", "kind_detail": p["place"],
                               "name": p.get("name"), "name:fa": p.get("name"), "min_zoom": 4 if city else 11,
                               "population_rank": 14 if city else 6}
            layers["places"].append(f)
        elif p.get("amenity") and p.get("name"):
            f["properties"] = {"kind": p["amenity"], "name": p["name"], "name:fa": p["name"], "min_zoom": 15}
            layers["pois"].append(f)
    args = []
    for name, feats in layers.items():
        path = Path(d) / f"pm_{name}.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False))
        args += ["-L", f"{name}:{path}"]
    subprocess.run(["tippecanoe", "-o", dest, "--force", "-z15", "-Z0", "--no-tile-size-limit",
                    "--no-feature-limit", "--no-tile-compression", "-q", *args], check=True)
    print(dest, {k: len(v) for k, v in layers.items()})
