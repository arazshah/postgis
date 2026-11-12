"""اعتبارسنجی هندسه‌ی GeoJSON برای فیلد `geometry` (ADR-0009 مرحله‌ی ۳).

اینجا فقط **ساختار و کران‌ها** سنجیده می‌شود (نوع، مختصات متناهی و در بازه‌ی جغرافیایی، حلقه‌ی بسته، سقف رأس و حجم)؛
درستی توپولوژی (مثلاً خودتقاطعی) را PostGIS با `ST_IsValid` می‌سنجد (pagekit.insert_rows). مختصات همیشه EPSG:4326 و (lon, lat) است.
"""
from __future__ import annotations

import json
import math

MAX_BYTES, MAX_VERTICES, MAX_PARTS = 200_000, 2000, 50
KINDS = {"point": "Point", "line": "LineString", "polygon": "Polygon", "multipolygon": "MultiPolygon"}
PG_TYPES = {"point": "Point", "line": "LineString", "polygon": "Polygon", "multipolygon": "MultiPolygon"}


class GeomValue(str):
    """متن GeoJSON هنجارشده‌ی یک هندسه (نشانه‌ی «این مقدار هندسه است» برای insert_rows)."""


def _pos(p, label: str) -> int:
    if not isinstance(p, (list, tuple)) or len(p) not in (2, 3) or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in p):
        raise ValueError(f"«{label}»: مختصات نامعتبر است.")
    x, y = float(p[0]), float(p[1])
    if not (math.isfinite(x) and math.isfinite(y)) or not -180 <= x <= 180 or not -90 <= y <= 90:
        raise ValueError(f"«{label}»: مختصات باید طول ۱۸۰- تا ۱۸۰ و عرض ۹۰- تا ۹۰ باشد.")
    return 1


def _ring(r, label: str) -> int:
    if not isinstance(r, list) or len(r) < 4:
        raise ValueError(f"«{label}»: هر حلقه دست‌کم ۴ نقطه دارد (۳ رأس و بستن).")
    n = sum(_pos(p, label) for p in r)
    if list(r[0][:2]) != list(r[-1][:2]):
        raise ValueError(f"«{label}»: حلقه بسته نیست (نقطه‌ی اول و آخر یکی باشد).")
    return n


def _polygon(c, label: str) -> int:
    if not isinstance(c, list) or not c or len(c) > MAX_PARTS:
        raise ValueError(f"«{label}»: چندضلعی نامعتبر است.")
    return sum(_ring(r, label) for r in c)


def validate(text: str, kind: str, label: str = "هندسه") -> GeomValue:
    """متن GeoJSON (هندسه یا Feature) ← GeomValue هنجارشده؛ ValueError با پیام فارسی."""
    if kind not in KINDS:
        raise ValueError(f"«{label}»: نوع هندسه‌ی ناشناخته.")
    if len(text) > MAX_BYTES:
        raise ValueError(f"«{label}» بیش از حد بزرگ است.")
    try:
        g = json.loads(text)
    except ValueError:
        raise ValueError(f"«{label}»: GeoJSON معتبر نیست.") from None
    if isinstance(g, dict) and g.get("type") == "Feature":
        g = g.get("geometry")
    if not isinstance(g, dict) or g.get("type") != KINDS[kind]:
        raise ValueError(f"«{label}» باید از نوع {KINDS[kind]} باشد.")
    c = g.get("coordinates")
    if kind == "point":
        n = _pos(c, label)
    elif kind == "line":
        if not isinstance(c, list) or len(c) < 2:
            raise ValueError(f"«{label}»: خط دست‌کم ۲ نقطه دارد.")
        n = sum(_pos(p, label) for p in c)
    elif kind == "polygon":
        n = _polygon(c, label)
    else:
        if not isinstance(c, list) or not c or len(c) > MAX_PARTS:
            raise ValueError(f"«{label}»: چندچندضلعی نامعتبر است.")
        n = sum(_polygon(p, label) for p in c)
    if n > MAX_VERTICES:
        raise ValueError(f"«{label}»: حداکثر {MAX_VERTICES} رأس مجاز است.")
    return GeomValue(json.dumps({"type": KINDS[kind], "coordinates": c}, separators=(",", ":")))
