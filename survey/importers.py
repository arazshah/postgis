"""ورود فایل به پروژه برداشت: CSV یا TXT نقاط و GeoJSON. خروجی: فهرست آیتم برای sync.apply."""
import csv
import io
import json
import math
import uuid

MAX_BYTES = 5 * 1024 * 1024
ORDERS = {"pen": ("pt_no", "x", "y", "z", "code"), "pne": ("pt_no", "y", "x", "z", "code"),
          "en": ("x", "y"), "ne": ("y", "x")}
ALIASES = {
    "pt_no": {"pt_no", "pt", "point", "name", "id", "no", "number", "شماره", "نام", "نقطه"},
    "x": {"x", "e", "east", "easting", "lon", "long", "longitude", "شرق", "طول"},
    "y": {"y", "n", "north", "northing", "lat", "latitude", "شمال", "عرض"},
    "z": {"z", "h", "elev", "elevation", "height", "ارتفاع"},
    "code": {"code", "desc", "description", "کد"},
    "descr": {"descr", "note", "notes", "comment", "توضیح"},
}


class ImportError_(ValueError):
    pass


def _decode(raw: bytes) -> str:
    if len(raw) > MAX_BYTES:
        raise ImportError_("حجم فایل بیش از ۵ مگابایت است.")
    for enc in ("utf-8-sig", "cp1256"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ImportError_("کدگذاری فایل خوانده نشد؛ آن را با UTF-8 ذخیره کنید.")


def _float(v):
    try:
        f = float(str(v).strip().replace("٫", ".").replace(",", ".") if v is not None else "")
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def _delim(text: str) -> str:
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    for d in (",", ";", "\t"):
        if d in first:
            return d
    return " "


def parse_points(raw: bytes, order: str, crs: str, project_srid: int) -> tuple[list[dict], list[str]]:
    """crs: "project" (مختصات پروژه) یا "4326" (طول و عرض). خطاهای سطری برگردانده می‌شوند، نه پرتاب."""
    if order not in ORDERS:
        raise ImportError_("ترتیب ستون‌ها نامعتبر است.")
    srid = project_srid if crs == "project" else 4326
    text = _decode(raw)
    d = _delim(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=d)) if d != " " else [ln.split() for ln in text.splitlines()]
    rows = [[c.strip() for c in r] for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ImportError_("فایل خالی است.")
    names = list(ORDERS[order])
    ix, iy = names.index("x"), names.index("y")
    first = rows[0]
    is_header = len(first) <= max(ix, iy) or _float(first[ix]) is None or _float(first[iy]) is None
    if is_header:
        mapped = {}
        for i, c in enumerate(c.lower() for c in first):
            for key, al in ALIASES.items():
                if c in al and key not in mapped.values():
                    mapped[i] = key
        if "x" in mapped.values() and "y" in mapped.values():
            names = [mapped.get(i) for i in range(len(first))]
        rows = rows[1:]
    items, errors = [], []
    for n, r in enumerate(rows, start=1):
        rec = dict(zip(names, r, strict=False))
        x, y = _float(rec.get("x")), _float(rec.get("y"))
        if x is None or y is None:
            errors.append(f"سطر {n}: مختصات نامعتبر")
            continue
        if srid == 4326 and not (-180 <= x <= 180 and -90 <= y <= 90):
            errors.append(f"سطر {n}: طول و عرض خارج از بازه")
            continue
        z = _float(rec.get("z"))
        props = {"pt_no": rec.get("pt_no") or None, "code": rec.get("code") or None, "descr": rec.get("descr") or None,
                 "pos_source": "file"}
        if z is not None:
            props["h_ortho"] = z
        items.append({"client_uuid": str(uuid.uuid4()), "kind": "point", "srid": srid,
                      "geometry": {"type": "Point", "coordinates": [x, y]},
                      "properties": {k: v for k, v in props.items() if v is not None}})
    return items, errors


def parse_geojson(raw: bytes) -> tuple[list[dict], list[str]]:
    try:
        data = json.loads(_decode(raw))
    except json.JSONDecodeError:
        raise ImportError_("فایل GeoJSON معتبر نیست.") from None
    feats = data.get("features") if isinstance(data, dict) and data.get("type") == "FeatureCollection" else \
        [data] if isinstance(data, dict) and data.get("type") == "Feature" else None
    if feats is None:
        raise ImportError_("فایل باید FeatureCollection باشد.")
    kinds = {"Point": "point", "LineString": "line", "Polygon": "polygon"}
    items, errors = [], []
    for i, f in enumerate(feats, start=1):
        g = (f or {}).get("geometry") or {}
        kind = kinds.get(g.get("type"))
        if not kind:
            errors.append(f"ویژگی {i}: نوع هندسه پشتیبانی نمی‌شود ({g.get('type')})")
            continue
        props = dict(f.get("properties") or {})
        props["pos_source"] = "file"
        items.append({"client_uuid": str(uuid.uuid4()), "kind": kind, "srid": 4326, "geometry": g,
                      "properties": {k: v for k, v in props.items() if isinstance(v, (str, int, float))}})
    return items, errors
