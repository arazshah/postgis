"""محاسبات مختصاتی (COGO) روی مختصات مسطح پروژه. زاویه‌ها گرادیان نیستند؛ درجه‌ی هندسی از شمال و ساعتگرد."""
import math


def inverse(p1, p2) -> dict:
    """فاصله افقی و آزیموت (۰ تا ۳۶۰ درجه از شمال، ساعتگرد) از p1 به p2."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    return {"distance": math.hypot(dx, dy), "azimuth": math.degrees(math.atan2(dx, dy)) % 360}


def forward(p, azimuth_deg: float, distance: float):
    a = math.radians(azimuth_deg)
    return (p[0] + distance * math.sin(a), p[1] + distance * math.cos(a))


def area_perimeter(ring) -> dict:
    """مساحت (شولیس) و محیط یک حلقه؛ نقطه آخر لازم نیست با اول یکی باشد."""
    pts = list(ring)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        raise ValueError("حداقل سه نقطه لازم است.")
    s = per = 0.0
    for i, (x1, y1) in enumerate(pts):
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
        per += math.hypot(x2 - x1, y2 - y1)
    return {"area": abs(s) / 2, "perimeter": per, "clockwise": s < 0}


def intersect_bearings(p1, az1, p2, az2):
    """تقاطع دو نیم‌خط با آزیموت؛ None اگر موازی."""
    d1 = (math.sin(math.radians(az1)), math.cos(math.radians(az1)))
    d2 = (math.sin(math.radians(az2)), math.cos(math.radians(az2)))
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-12:
        return None
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / den
    return (p1[0] + t * d1[0], p1[1] + t * d1[1])


def intersect_distances(p1, r1, p2, r2):
    """تقاطع دو دایره (دو جواب یا خالی)."""
    d = math.dist(p1, p2)
    if d == 0 or d > r1 + r2 or d < abs(r1 - r2):
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(r1 * r1 - a * a, 0))
    ex, ey = (p2[0] - p1[0]) / d, (p2[1] - p1[1]) / d
    mx, my = p1[0] + a * ex, p1[1] + a * ey
    return [(mx + h * ey, my - h * ex), (mx - h * ey, my + h * ex)] if h else [(mx, my)]


def traverse(start, start_azimuth, legs, closing_to=None) -> dict:
    """پیمایش: legs = [(زاویه گردش به راست نسبت به ضلع قبل بر حسب درجه, فاصله)].
    اگر closing_to داده شود خطای بسته‌شدن و دقت نسبی (۱/N) بر پایه‌ی طول کل گزارش می‌شود (بدون توزیع خطا)."""
    pts, az, cur = [tuple(start)], start_azimuth % 360, tuple(start)
    total = 0.0
    for turn, dist in legs:
        az = (az + turn) % 360
        cur = forward(cur, az, dist)
        total += dist
        pts.append(cur)
    out = {"points": pts, "length": total}
    if closing_to is not None:
        err = math.dist(cur, closing_to)
        out["misclosure"] = err
        out["precision"] = (total / err) if err > 1e-9 else math.inf
    return out


def stakeout(current, target) -> dict:
    """فاصله و جهت رسیدن از موقعیت فعلی به نقطه هدف؛ dx و dy یعنی چقدر به شرق و شمال بروید."""
    inv = inverse(current, target)
    return {**inv, "dx": target[0] - current[0], "dy": target[1] - current[1]}
