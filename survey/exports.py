"""خروجی‌های پروژه: CSV نقاط، GeoJSON، DXF و گزارش چاپی. مختصات همیشه در سیستم مختصات پروژه است."""
import csv
import io
import json

from django.utils.html import escape

from .dxf import Dxf


def points_csv(fc: dict, project) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["pt_no", "easting" if project.srid != 4326 else "lon", "northing" if project.srid != 4326 else "lat",
                "h_ortho", "h_ellip", "code", "descr", "fix_quality", "sats", "hdop", "acc_h", "captured_at"])
    for f in fc["features"]:
        p = f["properties"]
        w.writerow([p.get("pt_no") or p["id"], _n(p["x"]), _n(p["y"]), _n(p.get("h_ortho")), _n(p.get("h_ellip")),
                    p.get("code") or "", p.get("descr") or "", _n(p.get("fix_quality")), _n(p.get("sats")),
                    _n(p.get("hdop")), _n(p.get("acc_h")), p.get("captured_at") or ""])
    return "﻿" + buf.getvalue()  # BOM تا Excel فارسی را درست بخواند


def _n(v):
    return "" if v is None else (round(v, 4) if isinstance(v, float) else v)


def geojson(cols: dict) -> str:
    feats = [f for c in cols.values() for f in c["features"]]
    return json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False)


def dxf_file(cols: dict, project, projected: dict | None = None) -> str:
    """projected: {"lines": [[(x,y)…]], "polygons": [[(x,y)…]]} مختصات پروژه که از PostGIS خوانده شده است."""
    d = Dxf()
    for f in cols["points"]["features"]:
        p = f["properties"]
        d.point(p["x"], p["y"], p.get("h_ortho") or p.get("h_ellip") or 0.0, p.get("code") or "POINTS",
                p.get("pt_no") or str(p["id"]))
    projected = projected or {}
    for coords, f in zip(projected.get("lines", []), cols["lines"]["features"], strict=False):
        d.polyline(coords, f["properties"].get("code") or "LINES")
    for coords, f in zip(projected.get("polygons", []), cols["polygons"]["features"], strict=False):
        d.polyline(coords, f["properties"].get("code") or "POLYGONS", closed=True)
    return d.dumps()


def report_html(cols: dict, project, db_name: str) -> str:
    rows = []
    for f in cols["points"]["features"]:
        p = f["properties"]
        rows.append("<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in (
            p.get("pt_no") or p["id"], _n(p["x"]), _n(p["y"]), _n(p.get("h_ortho")) or _n(p.get("h_ellip")),
            p.get("code") or "", p.get("descr") or "", _n(p.get("acc_h")))) + "</tr>")
    return (f"<h1>{escape(project.name)}</h1><p>سیستم مختصات: EPSG:{project.srid} — پایگاه داده {escape(db_name)}</p>"
            "<table><thead><tr><th>شماره</th><th>شرق / طول</th><th>شمال / عرض</th><th>ارتفاع</th><th>کد</th>"
            "<th>توضیح</th><th>دقت (m)</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def contours_dxf(lines: list[dict], labels: bool = True) -> str:
    """منحنی‌ها در لایه‌های CONTOUR و CONTOUR_INDEX با ارتفاع هر منحنی؛ برچسب فقط روی منحنی‌های اصلی."""
    d = Dxf()
    for c in lines:
        layer, color = ("CONTOUR_INDEX", 1) if c["index"] else ("CONTOUR", 8)
        d.polyline(c["coords"], layer, closed=c["closed"], z=c["level"], color=color)
        if labels and c["index"] and len(c["coords"]) > 1:
            x, y = c["coords"][len(c["coords"]) // 2]
            d.text(x, y, f"{c['level']:g}", "CONTOUR_LABEL", 1.0)
    return d.dumps()
