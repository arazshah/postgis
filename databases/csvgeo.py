"""
تشخیص ستون‌های مکانی CSV و آماده‌سازی آن برای GDAL.

مشکل: ستون طول و عرض در فایل‌های واقعی نام‌های بسیار متفاوتی دارد (Longitude، X_coord، «طول جغرافیایی»،
Easting، «مختصات» به شکل «35.7, 51.4» و ...)، رقم‌ها گاهی فارسی‌اند (۵۱٫۴) یا درجه-دقیقه-ثانیه.
GDAL فقط نام‌های از پیش گفته‌شده را می‌شناسد و در غیر این صورت ستون geom خالی می‌ماند.

راه‌حل:
1. analyze: انکودینگ و جداکننده را تشخیص می‌دهد، ستون‌ها را از روی نام و از روی مقدار (محدوده عددی) بررسی
   می‌کند و یک پیشنهاد می‌دهد: xy (دو ستون)، pair (یک ستون «عرض، طول»)، wkt یا none.
   اگر طول و عرض جابه‌جا باشند (مثلاً x بین ۲۵ و ۴۰ و y بین ۴۴ و ۶۳ برای ایران) خودش جابه‌جا می‌کند.
2. prepare: فایل را به یک CSV استاندارد UTF-8 با ستون‌های gp_x/gp_y (یا gp_wkt) بازنویسی می‌کند؛
   رقم فارسی، ممیز فارسی، درجه-دقیقه-ثانیه و EWKT را تبدیل می‌کند و سطرهای نامعتبر را می‌شمارد.
   GDAL فقط همین ستون‌ها را به‌عنوان هندسه می‌خواند (بدون حدس دوباره).
کاربر در صفحه بررسی می‌تواند ستون‌ها را دستی هم انتخاب کند.
"""
from __future__ import annotations

import csv
import math
import re
from pathlib import Path

PREPARED_DIR = "gp_csv"  # gdal._open_options فایل‌های این پوشه را آماده‌شده می‌داند
COL_X, COL_Y, COL_WKT = "gp_x", "gp_y", "gp_wkt"
MODES = ("xy", "pair", "wkt", "none")
ENCODINGS = {"UTF-8": "utf-8-sig", "CP1256": "cp1256", "UTF-16": "utf-16"}
SCAN_ROWS = 1000
SAMPLE_ROWS = 5
MAX_COLS = 200

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_ARABIC = str.maketrans({"ي": "ی", "ك": "ک", "ئ": "ی", "‌": "", "‏": "", "‎": "", "﻿": ""})


# ---------------------------------------------------------------------- نام ستون‌ها
def norm_name(name: str) -> str:
    """کوچک، بدون فاصله و نیم‌فاصله و علامت؛ ي/ك عربی به فارسی."""
    s = (name or "").translate(_ARABIC).strip().lower()
    return re.sub(r"[^0-9a-z؀-ۿ]+", "", s)


def _names(*items: str) -> set[str]:
    return {norm_name(i) for i in items}


X_EXACT = _names(
    "lon", "lng", "long", "longitude", "longitud", "longtitude", "longitute", "x", "xcoord", "xcoordinate",
    "coordx", "coord_x", "pointx", "point_x", "posx", "gpsx", "gps_lon", "gps_long", "gpslongitude",
    "easting", "east", "utmx", "utm_x", "utme", "utm_e", "e", "xutm", "lon_dd", "long_dd", "lon_deg",
    "طول", "طول جغرافیایی", "طول جغرافيايي", "طول_جغرافیایی", "طول‌جغرافیایی", "طول جغرافیائی",
    "مختصات x", "x مختصات", "ایکس", "شرقی", "طول شرقی", "lambda",
)
Y_EXACT = _names(
    "lat", "latitude", "latitud", "lattitude", "y", "ycoord", "ycoordinate", "coordy", "coord_y", "pointy",
    "point_y", "posy", "gpsy", "gps_lat", "gpslatitude", "northing", "north", "utmy", "utm_y", "utmn",
    "utm_n", "n", "yutm", "lat_dd", "lat_deg",
    "عرض", "عرض جغرافیایی", "عرض جغرافيايي", "عرض_جغرافیایی", "عرض‌جغرافیایی", "عرض جغرافیائی",
    "مختصات y", "y مختصات", "وای", "شمالی", "عرض شمالی", "phi",
)
X_PART = ("longitude", "longitud", "lng", "lon", "easting", "طول", "xcoord", "coordx", "utmx", "شرقی")
Y_PART = ("latitude", "latitud", "lat", "northing", "عرض", "ycoord", "coordy", "utmy", "شمالی")
# «lon» داخل کلمه‌هایی مثل colony و «lat» داخل plate/flat/translate نباید شمرده شوند
_PART_STOP = ("colon", "salon", "along", "plate", "flat", "translat", "relat", "platform", "slat", "latest",
              "calculat", "populat", "regulat", "simulat", "isolat", "violat", "lattice")
WKT_EXACT = _names("wkt", "geom", "geometry", "the_geom", "shape", "geo", "هندسه", "شکل", "wkt_geom", "geom_wkt")
PAIR_EXACT = _names(
    "latlon", "latlng", "lat_lon", "lat_long", "lonlat", "lnglat", "lon_lat", "long_lat", "coordinates",
    "coordinate", "coords", "coord", "location", "loc", "position", "point", "gps", "latlong", "longlat",
    "مختصات", "موقعیت", "مکان", "لوکیشن", "نقطه", "مختصات جغرافیایی", "موقعیت جغرافیایی",
)


def _name_score(norm: str, exact: set[str], parts: tuple[str, ...], raw: str = "") -> int:
    if norm in exact:
        return 3
    tokens = [t for t in re.split(r"[^0-9a-z\u0600-\u06ff]+", (raw or "").translate(_ARABIC).lower()) if t]
    if len(tokens) > 1 and any(t in exact and len(t) > 1 for t in tokens):  # gps_long_deg ← long
        return 2
    if any(stop in norm for stop in _PART_STOP):
        return 0
    if any(norm.startswith(p) or norm.endswith(p) for p in parts):
        return 2
    if any(p in norm for p in parts if len(p) >= 4):
        return 1
    return 0


# ---------------------------------------------------------------------- مقدارها
_DMS = re.compile(
    r"^\s*([NSEWشجقغ])?\s*(-?\d+(?:\.\d+)?)\s*(?:°|º|d|deg|درجه|\s)\s*"
    r"(?:(\d+(?:\.\d+)?)\s*(?:'|′|’|m|min|دقیقه|\s)\s*)?"
    r"(?:(\d+(?:\.\d+)?)\s*(?:\"|″|”|''|s|sec|ثانیه)?\s*)?([NSEWشجقغ])?\s*$",
    re.IGNORECASE,
)
_NEG_HEMI = {"s", "w", "ج", "غ"}


def clean_number_text(value: str) -> str:
    s = (value or "").strip().translate(_DIGITS)
    s = s.replace("٫", ".").replace("٬", "").replace("−", "-").replace(" ", "").replace(" ", " ")
    if "," in s and "." not in s and s.count(",") == 1:  # ممیز اروپایی: 51,4
        s = s.replace(",", ".")
    return s


def parse_number(value) -> float | None:
    """عدد اعشاری، رقم فارسی/عربی، ممیز فارسی و درجه-دقیقه-ثانیه (35°41'22"N)."""
    if value is None:
        return None
    s = clean_number_text(str(value))
    if not s:
        return None
    try:
        v = float(s)
        return v if math.isfinite(v) else None
    except ValueError:
        pass
    m = _DMS.match(s)
    if not m or (m.group(3) is None and m.group(1) is None and m.group(5) is None):
        return None
    deg = float(m.group(2))
    minutes = float(m.group(3) or 0)
    seconds = float(m.group(4) or 0)
    if minutes >= 60 or seconds >= 60:
        return None
    v = abs(deg) + minutes / 60 + seconds / 3600
    hemi = (m.group(1) or m.group(5) or "").lower()
    if deg < 0 or hemi in _NEG_HEMI:
        v = -v
    return v


_PAIR_SPLIT = re.compile(r"\s*[,;/|،؛]\s*|\s+")


def parse_pair(value) -> tuple[float, float] | None:
    """«35.7, 51.4» یا «35.7 51.4» یا «(35.7;51.4)» → دو عدد به همان ترتیب فایل."""
    if value is None:
        return None
    s = (str(value) or "").strip().translate(_DIGITS).replace("٫", ".").replace("٬", ",")
    s = s.strip("()[]{} ")
    if not s or s.upper().startswith(("POINT", "SRID")):
        return None
    parts = [p for p in _PAIR_SPLIT.split(s) if p]
    if len(parts) != 2:
        return None
    a, b = parse_number(parts[0]), parse_number(parts[1])
    if a is None or b is None:
        return None
    return a, b


_WKT_RE = re.compile(r"^\s*(SRID=(\d+);)?\s*(MULTI)?(POINT|LINESTRING|POLYGON|GEOMETRYCOLLECTION)\s*(Z|M|ZM)?\s*\(",
                     re.IGNORECASE)


def parse_wkt(value) -> tuple[str, int | None] | None:
    m = _WKT_RE.match(value or "")
    if not m:
        return None
    srid = int(m.group(2)) if m.group(2) else None
    return value[m.end(1):].strip() if m.group(1) else value.strip(), srid


# ---------------------------------------------------------------------- خواندن فایل
def detect_encoding(path: Path) -> str:
    head = _head(path, 2_000_000)
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "UTF-16"
    try:
        head.decode("utf-8")
        return "UTF-8"
    except UnicodeDecodeError as exc:
        if exc.start >= len(head) - 3:  # برش وسط یک حرف چندبایتی
            return "UTF-8"
        return "CP1256"


def _head(path: Path, n: int) -> bytes:
    with open(path, "rb") as f:
        return f.read(n)


def _open_text(path: Path, encoding: str):
    return open(path, encoding=ENCODINGS.get(encoding, "utf-8-sig"), errors="replace", newline="")


def detect_delimiter(first_line: str) -> str:
    counts = {d: first_line.count(d) for d in (",", ";", "\t", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def _reader(f, delimiter: str):
    csv.field_size_limit(16 * 1024 * 1024)  # WKT پلیگون‌های بزرگ
    return csv.reader(f, delimiter=delimiter)


# ---------------------------------------------------------------------- تحلیل
def _profile(columns: list[str], rows: list[list[str]]) -> list[dict]:
    prof = []
    for i, name in enumerate(columns):
        vals = [r[i].strip() for r in rows if i < len(r) and r[i].strip()]
        nums = [v for v in (parse_number(x) for x in vals) if v is not None]
        decimals = sum(1 for x in vals if re.search(r"[.٫]\d|°|'", x.translate(_DIGITS)))
        pairs = [p for p in (parse_pair(x) for x in vals) if p]
        wkts = [w for w in (parse_wkt(x) for x in vals) if w]
        n = len(vals) or 1
        prof.append({
            "name": name, "norm": norm_name(name), "filled": len(vals),
            "numeric": len(nums) / n if vals else 0.0, "decimal": decimals / n if vals else 0.0,
            "min": min(nums) if nums else None, "max": max(nums) if nums else None,
            "pair": len(pairs) / n if vals else 0.0, "pairs": pairs[:200],
            "wkt": len(wkts) / n if vals else 0.0,
            "wkt_srid": next((s for _, s in wkts if s), None),
        })
    return prof


def _in(p: dict, lo: float, hi: float) -> bool:
    return p["min"] is not None and p["min"] >= lo and p["max"] <= hi


def _is_lon(p):  # طول جغرافیایی
    return _in(p, -180, 180)


def _is_lat(p):
    return _in(p, -90, 90)


def _iran_lon(p):
    return _in(p, 43, 64)


def _iran_lat(p):
    return _in(p, 24, 40.5)


def _is_easting(p):
    return _in(p, 100_000, 900_000)


def _is_northing(p):
    return _in(p, 0, 10_000_000) and p["max"] > 900_000


def _suggest_xy(prof: list[dict]) -> dict | None:
    numeric = [p for p in prof if p["filled"] and p["numeric"] >= 0.8]
    if len(numeric) < 2:
        return None
    # ۱) از روی نام
    xs = sorted(((_name_score(p["norm"], X_EXACT, X_PART, p["name"]), p) for p in numeric), key=lambda t: -t[0])
    ys = sorted(((_name_score(p["norm"], Y_EXACT, Y_PART, p["name"]), p) for p in numeric), key=lambda t: -t[0])
    for sx, px in xs:
        if not sx:
            break
        for sy, py in ys:
            if not sy or py is px:
                continue
            return _orient(px, py, "name")
    # ۲) از روی مقدارها: دو ستون اعشاری که یکی در محدوده طول و دیگری در محدوده عرض باشد
    dec = [p for p in numeric if p["decimal"] >= 0.5]
    for a in dec:
        for b in dec:
            if a is b:
                continue
            if _iran_lon(a) and _iran_lat(b):
                return _orient(a, b, "content")
    for a in dec:
        for b in dec:
            if a is not b and _is_lon(a) and _is_lat(b) and not _is_lat(a):
                return _orient(a, b, "content")
    # ۳) مختصات تصویری (UTM): Easting شش‌رقمی و Northing بزرگ‌تر
    for a in numeric:
        for b in numeric:
            if a is not b and _is_easting(a) and _is_northing(b) and b["min"] > a["max"]:
                return _orient(a, b, "content")
    return None


def _orient(px: dict, py: dict, how: str) -> dict:
    """اگر طول و عرض جابه‌جا نوشته شده باشند، برمی‌گرداند. SRID را از محدوده حدس می‌زند."""
    swapped = False
    iran_swapped = _iran_lat(px) and _iran_lon(py) and not (_iran_lon(px) and _iran_lat(py))
    world_swapped = _is_lat(px) and _is_lon(py) and not _is_lat(py)  # بیرون از ±۹۰ نمی‌تواند عرض باشد
    if iran_swapped or world_swapped:
        px, py, swapped = py, px, True
    spec = {"mode": "xy", "x": px["name"], "y": py["name"], "how": how, "swapped": swapped}
    spec.update(_srid_guess(px, py))
    return spec


def _srid_guess(px: dict, py: dict) -> dict:
    if _is_lon(px) and _is_lat(py):
        return {"srid": 4326, "kind": "geographic"}
    if _is_easting(px) and _is_northing(py):
        return {"srid": None, "kind": "utm"}
    if _in(px, -20_037_509, 20_037_509) and _in(py, -20_048_967, 20_048_967) and abs(px["max"] or 0) > 1_000_000:
        return {"srid": 3857, "kind": "mercator"}
    return {"srid": None, "kind": "unknown"}


def guess_srid(stats: dict) -> int | None:
    """SRID از محدوده مختصات خوانده‌شده (فقط وقتی قطعی است: طول و عرض جغرافیایی)."""
    if stats.get("xmin") is None or stats.get("srid"):
        return stats.get("srid")
    px = {"min": stats["xmin"], "max": stats["xmax"]}
    py = {"min": stats["ymin"], "max": stats["ymax"]}
    return _srid_guess(px, py)["srid"]


def _suggest_pair(prof: list[dict]) -> dict | None:
    cands = [p for p in prof if p["filled"] and p["pair"] >= 0.8]
    if not cands:
        return None
    cands.sort(key=lambda p: (-_name_score(p["norm"], PAIR_EXACT, ()), -p["pair"]))
    p = cands[0]
    first = [a for a, _ in p["pairs"]]
    second = [b for _, b in p["pairs"]]
    f = {"min": min(first), "max": max(first)}
    s = {"min": min(second), "max": max(second)}
    # پیش‌فرض گوگل‌مپ: «عرض، طول». اگر اولی بیرون از ±۹۰ یا محدوده ایران برعکس است، «طول، عرض».
    lonlat = (not _is_lat(f) and _is_lat(s)) or (_iran_lon(f) and _iran_lat(s))
    if _is_easting(f) and _is_northing(s):
        lonlat = True
    order = "lonlat" if lonlat else "latlon"
    px, py = (f, s) if lonlat else (s, f)
    spec = {"mode": "pair", "pair": p["name"], "pair_order": order, "how": "content", "swapped": False}
    spec.update(_srid_guess(px, py))
    return spec


def suggest(prof: list[dict]) -> dict:
    wkt = [p for p in prof if p["filled"] and p["wkt"] >= 0.8]
    if wkt:
        wkt.sort(key=lambda p: -_name_score(p["norm"], WKT_EXACT, ()))
        srid = wkt[0]["wkt_srid"]
        return {"mode": "wkt", "geom": wkt[0]["name"], "how": "content", "swapped": False,
                "srid": srid, "kind": "wkt"}
    return _suggest_xy(prof) or _suggest_pair(prof) or {"mode": "none", "how": "", "swapped": False,
                                                        "srid": None, "kind": "none"}


def analyze(path: Path, encoding: str | None = None) -> dict:
    """انکودینگ، جداکننده، ستون‌ها، چند سطر نمونه و پیشنهاد ستون‌های مکانی."""
    encoding = encoding if encoding in ENCODINGS else detect_encoding(path)
    with _open_text(path, encoding) as f:
        first = f.readline()
        delimiter = detect_delimiter(first)
        f.seek(0)
        reader = _reader(f, delimiter)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("فایل CSV خالی است.") from None
        rows = []
        for i, row in enumerate(reader):
            if i >= SCAN_ROWS:
                break
            if any(c.strip() for c in row):
                rows.append(row)
    columns = _unique_columns(header)[:MAX_COLS]
    if not columns:
        raise ValueError("سطر اول فایل CSV باید نام ستون‌ها باشد.")
    prof = _profile(columns, rows)
    spec = suggest(prof)
    sample = [[(r[i] if i < len(r) else "")[:60] for i in range(len(columns))] for r in rows[:SAMPLE_ROWS]]
    return {"encoding": encoding, "delimiter": delimiter, "columns": columns, "sample": sample,
            "spec": spec, "auto": dict(spec)}


def _unique_columns(header: list[str]) -> list[str]:
    seen, out = {}, []
    for i, h in enumerate(header):
        name = (h or "").replace("﻿", "").strip() or f"field_{i + 1}"
        base, n = name, 2
        while name in seen:
            name, n = f"{base}_{n}", n + 1
        seen[name] = True
        out.append(name)
    return out


# ---------------------------------------------------------------------- اعتبارسنجی انتخاب کاربر
def clean_spec(columns: list[str], data: dict) -> tuple[dict, list[str]]:
    """داده فرم (mode، x، y، pair، pair_order، geom) → spec معتبر و فهرست خطاها."""
    mode = data.get("mode") if data.get("mode") in MODES else "none"
    spec = {"mode": mode, "how": "manual", "swapped": False}
    errors = []
    if mode == "xy":
        x, y = data.get("x"), data.get("y")
        if x not in columns or y not in columns:
            errors.append("ستون طول (X) و ستون عرض (Y) را انتخاب کنید.")
        elif x == y:
            errors.append("ستون طول و ستون عرض نمی‌توانند یکی باشند.")
        spec.update(x=x, y=y)
    elif mode == "pair":
        if data.get("pair") not in columns:
            errors.append("ستونی را که طول و عرض با هم در آن نوشته شده است انتخاب کنید.")
        spec.update(pair=data.get("pair"), pair_order="lonlat" if data.get("pair_order") == "lonlat" else "latlon")
    elif mode == "wkt":
        if data.get("geom") not in columns:
            errors.append("ستون هندسه (WKT) را انتخاب کنید.")
        spec.update(geom=data.get("geom"))
    return spec, errors


def same_spec(a: dict, b: dict) -> bool:
    keys = {"xy": ("x", "y"), "pair": ("pair", "pair_order"), "wkt": ("geom",), "none": ()}
    if (a or {}).get("mode") != (b or {}).get("mode"):
        return False
    return all(a.get(k) == b.get(k) for k in keys.get(a.get("mode"), ()))


# ---------------------------------------------------------------------- بازنویسی فایل
def prepared_path(folder: Path, original_name: str) -> Path:
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", Path(original_name or "data").stem).strip("_") or "data"
    return folder / PREPARED_DIR / f"{stem[:50]}.csv"


def prepare(src: Path, dst: Path, encoding: str, delimiter: str, spec: dict) -> dict:
    """CSV استاندارد (UTF-8، کاما) با gp_x/gp_y یا gp_wkt؛ ستون‌های مختصات اصلی حذف می‌شوند."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    mode = spec.get("mode", "none")
    stats = {"rows": 0, "bad": 0, "srid": None, "xmin": None, "xmax": None, "ymin": None, "ymax": None,
             "points": []}
    with _open_text(src, encoding) as f, open(dst, "w", encoding="utf-8", newline="") as out:
        reader = _reader(f, delimiter)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("فایل CSV خالی است.") from None
        columns = _unique_columns(header)
        idx = {c: i for i, c in enumerate(columns)}
        used = {"xy": [spec.get("x"), spec.get("y")], "pair": [spec.get("pair")],
                "wkt": [spec.get("geom")]}.get(mode, [])
        used_i = {idx[c] for c in used if c in idx}
        if mode != "none" and len(used_i) != len(used):
            raise ValueError("ستون انتخاب‌شده در فایل پیدا نشد.")
        keep = [i for i in range(len(columns)) if i not in used_i and columns[i] not in (COL_X, COL_Y, COL_WKT)]
        extra = {"xy": [COL_X, COL_Y], "pair": [COL_X, COL_Y], "wkt": [COL_WKT]}.get(mode, [])
        writer = csv.writer(out)
        writer.writerow([columns[i] for i in keep] + extra)
        for row in reader:
            if not any(c.strip() for c in row):
                continue
            stats["rows"] += 1
            vals = [row[i] if i < len(row) else "" for i in keep]
            geo = _geo_values(row, mode, spec, idx, stats)
            if geo is None:
                stats["bad"] += 1
                geo = [""] * len(extra)
            writer.writerow(vals + geo)
    return stats


def _cell(row, idx, name) -> str:
    i = idx.get(name)
    return row[i] if i is not None and i < len(row) else ""


def _geo_values(row, mode, spec, idx, stats) -> list[str] | None:
    if mode == "none":
        return []
    if mode == "wkt":
        parsed = parse_wkt(_cell(row, idx, spec["geom"]))
        if not parsed:
            return None
        if parsed[1] and not stats["srid"]:
            stats["srid"] = parsed[1]
        return [parsed[0]]
    if mode == "xy":
        x, y = parse_number(_cell(row, idx, spec["x"])), parse_number(_cell(row, idx, spec["y"]))
        if x is None or y is None:
            return None
    else:
        pair = parse_pair(_cell(row, idx, spec["pair"]))
        if not pair:
            return None
        y, x = pair if spec.get("pair_order") != "lonlat" else (pair[1], pair[0])
    for k, v in (("x", x), ("y", y)):
        stats[f"{k}min"] = v if stats[f"{k}min"] is None else min(stats[f"{k}min"], v)
        stats[f"{k}max"] = v if stats[f"{k}max"] is None else max(stats[f"{k}max"], v)
    if len(stats["points"]) < 3:
        stats["points"].append([round(x, 6), round(y, 6)])
    return [repr(x), repr(y)]


def range_check(stats: dict, srid: int | None) -> tuple[str, str]:
    """(سطح، پیام): «error» اگر با SRID جغرافیایی مقدارها بیرون از محدوده‌اند، «warn» اگر جابه‌جا به نظر می‌رسند."""
    if srid != 4326 or stats.get("xmin") is None:
        return "", ""
    if not (-180 <= stats["xmin"] and stats["xmax"] <= 180 and -90 <= stats["ymin"] and stats["ymax"] <= 90):
        return "error", ("مقدارهای مختصات بیرون از محدوده طول و عرض جغرافیایی‌اند؛ احتمالاً سیستم مختصات فایل "
                         "تصویری (مثلاً UTM) است یا ستون‌ها اشتباه انتخاب شده‌اند.")
    if 24 <= stats["xmin"] and stats["xmax"] <= 40.5 and 43 <= stats["ymin"] and stats["ymax"] <= 64:
        return "warn", "به نظر می‌رسد جای طول و عرض برعکس است (عرض در ستون X). اگر نقطه‌ها باید در ایران باشند، ستون‌ها را جابه‌جا کنید."
    return "", ""
