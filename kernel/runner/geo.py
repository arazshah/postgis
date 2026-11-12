"""کتابخانه‌ی مکانی برای handler سطح ۲ (`import geo`): فقط کتابخانه‌ی استاندارد، بدون شبکه و فایل.

برای پلاگین‌های GIS و سنجش‌ازدور (کشاورزی، آب، محیط‌زیست…): فاصله و جهت، مساحت و نقطه‌در‌چندضلعی، UTM، خواندن GeoJSON/WKT،
شاخص‌های طیفی (NDVI، NDWI، EVI، SAVI)، طبقه‌بندی، آمار، و محاسبه‌های اقلیمی (GDD، تابش فرازمینی، تبخیر-تعرق هارگریوز).
مختصات همیشه (lat, lon) به درجه (WGS84) است مگر خلاف آن گفته شود. تابع‌ها هرگز فایل/شبکه نمی‌خوانند و روی ورودی نامعتبر ValueError می‌دهند.
"""
import json
import math
import statistics

R_KM = 6371.0088  # شعاع میانگین زمین
_WGS84_A, _WGS84_F = 6378137.0, 1 / 298.257223563


def _chk(lat, lon):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"مختصات نامعتبر: ({lat}, {lon})")


# ---------------------------------------------------------------------- فاصله و جهت
def haversine_km(lat1, lon1, lat2, lon2):
    """فاصله‌ی دایره‌ی عظیمه بر حسب کیلومتر."""
    _chk(lat1, lon1)
    _chk(lat2, lon2)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """جهت اولیه از نقطه‌ی ۱ به ۲ (۰ تا ۳۶۰، از شمال، ساعتگرد)."""
    _chk(lat1, lon1)
    _chk(lat2, lon2)
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def destination(lat, lon, bearing, km):
    """نقطه‌ای که با حرکت `km` کیلومتر در جهت `bearing` از (lat, lon) می‌رسیم."""
    _chk(lat, lon)
    d, b, p1, l1 = km / R_KM, math.radians(bearing), math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def path_length_km(points):
    """طول مسیر (فهرست (lat, lon))."""
    return sum(haversine_km(a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:], strict=False))


# ---------------------------------------------------------------------- شکل‌ها
def bbox(points):
    """(min_lat, min_lon, max_lat, max_lon)."""
    if not points:
        raise ValueError("نقطه‌ای نیست.")
    lats, lons = [p[0] for p in points], [p[1] for p in points]
    return min(lats), min(lons), max(lats), max(lons)


def centroid(points):
    """میانگین ساده‌ی مختصات (برای محدوده‌های کوچک)."""
    if not points:
        raise ValueError("نقطه‌ای نیست.")
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


def point_in_polygon(lat, lon, ring):
    """نقطه داخل حلقه‌ی چندضلعی (فهرست (lat, lon)) است؟ (پرتو؛ مرز دقیق تضمین نمی‌شود)."""
    inside, n = False, len(ring)
    for i in range(n):
        y1, x1 = ring[i]
        y2, x2 = ring[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def polygon_area_km2(ring):
    """مساحت حلقه‌ی چندضلعی روی کره (کیلومتر مربع؛ خطای کم برای زمین کروی)."""
    if len(ring) < 3:
        return 0.0
    total, n = 0.0, len(ring)
    for i in range(n):
        lat1, lon1 = ring[i]
        lat2, lon2 = ring[(i + 1) % n]
        total += math.radians(lon2 - lon1) * (2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2)))
    return abs(total) * R_KM ** 2 / 2


# ---------------------------------------------------------------------- تصویرها
def utm_zone(lon):
    return int((lon + 180) // 6) % 60 + 1


def wgs84_to_utm(lat, lon, zone=None):
    """UTM (روی WGS84): {zone, hemisphere, easting, northing} بر حسب متر. ایران عمدتاً منطقه‌ی ۳۸ تا ۴۰ (N)."""
    _chk(lat, lon)
    zone = zone or utm_zone(lon)
    k0, a, f = 0.9996, _WGS84_A, _WGS84_F
    n = f / (2 - f)
    big_a = a / (1 + n) * (1 + n ** 2 / 4 + n ** 4 / 64)
    alpha = (n / 2 - 2 * n ** 2 / 3 + 5 * n ** 3 / 16 + 41 * n ** 4 / 180,
             13 * n ** 2 / 48 - 3 * n ** 3 / 5 + 557 * n ** 4 / 1440,
             61 * n ** 3 / 240 - 103 * n ** 4 / 140,
             49561 * n ** 4 / 161280)
    phi, dl = math.radians(lat), math.radians(lon - (zone * 6 - 183))
    c = 2 * math.sqrt(n) / (1 + n)
    t = math.sinh(math.atanh(math.sin(phi)) - c * math.atanh(c * math.sin(phi)))
    xi0 = math.atan2(t, math.cos(dl))
    eta0 = math.atanh(math.sin(dl) / math.sqrt(1 + t * t))
    xi = xi0 + sum(a_j * math.sin(2 * (j + 1) * xi0) * math.cosh(2 * (j + 1) * eta0) for j, a_j in enumerate(alpha))
    eta = eta0 + sum(a_j * math.cos(2 * (j + 1) * xi0) * math.sinh(2 * (j + 1) * eta0) for j, a_j in enumerate(alpha))
    return {"zone": zone, "hemisphere": "N" if lat >= 0 else "S", "easting": 500000 + k0 * big_a * eta,
            "northing": k0 * big_a * xi + (0 if lat >= 0 else 10000000)}


def web_mercator(lat, lon):
    """(x, y) متر در EPSG:3857."""
    if not -85.06 <= lat <= 85.06:
        raise ValueError("عرض خارج از محدوده‌ی مرکاتور وب.")
    return math.radians(lon) * 6378137.0, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * 6378137.0


# ---------------------------------------------------------------------- قالب‌ها
def parse_geojson(text, limit=20000):
    """GeoJSON (Feature، FeatureCollection یا هندسه) ← فهرست {type, coordinates, properties}."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError("GeoJSON معتبر نیست.") from exc
    out = []

    def walk(o, props=None):
        if len(out) >= limit:
            raise ValueError(f"بیش از {limit} عارضه.")
        if not isinstance(o, dict):
            raise ValueError("GeoJSON معتبر نیست.")
        t = o.get("type")
        if t == "FeatureCollection":
            for f in o.get("features") or []:
                walk(f)
        elif t == "Feature":
            g = o.get("geometry")
            if g:
                walk(g, o.get("properties") or {})
        elif t == "GeometryCollection":
            for g in o.get("geometries") or []:
                walk(g, props)
        elif t in ("Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"):
            out.append({"type": t, "coordinates": o.get("coordinates"), "properties": dict(props or {})})
        else:
            raise ValueError(f"نوع GeoJSON پشتیبانی نمی‌شود: {t}")

    walk(data)
    return out


def point_features(text, limit=20000):
    """فقط نقطه‌ها ← فهرست {lat, lon, properties} (MultiPoint باز می‌شود)."""
    pts = []
    for f in parse_geojson(text, limit):
        if f["type"] == "Point":
            coords = [f["coordinates"]]
        elif f["type"] == "MultiPoint":
            coords = f["coordinates"]
        else:
            continue
        for c in coords:
            lon, lat = float(c[0]), float(c[1])
            _chk(lat, lon)
            pts.append({"lat": lat, "lon": lon, "properties": f["properties"]})
    return pts


def to_geojson_points(rows, lat_key="lat", lon_key="lon"):
    """فهرست dict ← متن GeoJSON نقطه‌ها (بقیه‌ی کلیدها properties)."""
    feats = []
    for r in rows:
        lat, lon = float(r[lat_key]), float(r[lon_key])
        _chk(lat, lon)
        props = {k: v for k, v in r.items() if k not in (lat_key, lon_key)}
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props})
    return json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False)


def parse_wkt_point(text):
    """`POINT(lon lat)` ← (lat, lon)."""
    t = str(text).strip().upper()
    if not t.startswith("POINT") or "(" not in t or ")" not in t:
        raise ValueError("WKT نقطه نیست.")
    parts = t[t.index("(") + 1:t.index(")")].split()
    if len(parts) < 2:
        raise ValueError("WKT نقطه نیست.")
    lon, lat = float(parts[0]), float(parts[1])
    _chk(lat, lon)
    return lat, lon


# ---------------------------------------------------------------------- شاخص‌های طیفی
def _ratio(num, den):
    if den == 0:
        raise ValueError("مخرج صفر.")
    return num / den


def ndvi(nir, red):
    """(NIR − Red) / (NIR + Red)."""
    return _ratio(nir - red, nir + red)


def ndwi(green, nir):
    """(Green − NIR) / (Green + NIR) (آب‌نمایی McFeeters)."""
    return _ratio(green - nir, green + nir)


def evi(nir, red, blue, g=2.5, c1=6.0, c2=7.5, lval=1.0):
    return g * _ratio(nir - red, nir + c1 * red - c2 * blue + lval)


def savi(nir, red, lval=0.5):
    """شاخص پوشش گیاهی با تعدیل خاک."""
    return _ratio((nir - red) * (1 + lval), nir + red + lval)


def classify(value, breaks, labels):
    """مقدار را با مرزهای صعودی طبقه‌بندی می‌کند؛ len(labels) == len(breaks) + 1. مرز به طبقه‌ی بالاتر می‌رود."""
    if len(labels) != len(breaks) + 1 or list(breaks) != sorted(breaks):
        raise ValueError("مرزها باید صعودی و برچسب‌ها یکی بیشتر از مرزها باشند.")
    for b, label in zip(breaks, labels, strict=False):
        if value < b:
            return label
    return labels[-1]


def percentile(values, p):
    """صدک با درون‌یابی خطی (۰ تا ۱۰۰)."""
    v = sorted(values)
    if not v:
        raise ValueError("مقداری نیست.")
    if not 0 <= p <= 100:
        raise ValueError("صدک بین ۰ و ۱۰۰ است.")
    k = (len(v) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def stats(values):
    """{count, min, max, mean, median, stdev} (مقدار None نادیده گرفته می‌شود)."""
    v = [float(x) for x in values if x is not None]
    if not v:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None, "stdev": None}
    return {"count": len(v), "min": min(v), "max": max(v), "mean": statistics.fmean(v), "median": statistics.median(v),
            "stdev": statistics.pstdev(v) if len(v) > 1 else 0.0}


# ---------------------------------------------------------------------- اقلیم، کشاورزی، آب
def day_of_year(year, month, day):
    cum = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    return cum[month - 1] + day + (1 if leap and month > 2 else 0)


def gdd(tmin, tmax, base=10.0, cap=30.0):
    """درجه‌روز رشد (روش میانگین با کران پایین/بالا)."""
    lo, hi = max(tmin, base), min(max(tmax, base), cap)
    return max(0.0, (lo + hi) / 2 - base)


def extraterrestrial_radiation(lat, doy):
    """تابش فرازمینی Ra بر حسب MJ/m²/روز (FAO-56، معادله‌ی ۲۱)."""
    if not -90 <= lat <= 90 or not 1 <= doy <= 366:
        raise ValueError("ورودی نامعتبر.")
    phi = math.radians(lat)
    dr = 1 + 0.033 * math.cos(2 * math.pi / 365 * doy)
    delta = 0.409 * math.sin(2 * math.pi / 365 * doy - 1.39)
    x = max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta)))
    ws = math.acos(x)
    return 24 * 60 / math.pi * 0.0820 * dr * (ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws))


def et0_hargreaves(tmin, tmax, lat, doy):
    """تبخیر-تعرق مرجع روزانه (میلی‌متر) با روش هارگریوز-سامانی."""
    if tmax < tmin:
        raise ValueError("بیشینه‌ی دما از کمینه کمتر است.")
    ra_mm = extraterrestrial_radiation(lat, doy) * 0.408
    return max(0.0, 0.0023 * ((tmin + tmax) / 2 + 17.8) * math.sqrt(tmax - tmin) * ra_mm)
