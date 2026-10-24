"""
سطح و منحنی میزان از مثلث‌بندی TIN (مثلث‌های Delaunay که PostGIS می‌سازد).

هسته خالص و بدون پایگاه داده است تا با پاسخ تحلیلی آزموده شود. مثلث: ((x, y, z), (x, y, z), (x, y, z)).
"""
from __future__ import annotations

import math

MAX_LEVELS = 600
MAX_FEATURES = 20000


class SurfaceError(ValueError):
    """پیام فارسی قابل‌نمایش به کاربر."""


def area2d(t) -> float:
    (x0, y0, _), (x1, y1, _), (x2, y2, _) = t
    return abs((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)) / 2


def filter_long_edges(tris, max_edge: float | None):
    """مثلث‌های بلند لبه‌ی محدب (روی ناحیه‌های بدون برداشت) را حذف می‌کند."""
    if not max_edge:
        return list(tris)
    m2 = max_edge * max_edge
    out = []
    for t in tris:
        ok = True
        for i in range(3):
            a, b = t[i], t[(i + 1) % 3]
            if (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 > m2:
                ok = False
                break
        if ok:
            out.append(t)
    return out


def stats(tris) -> dict:
    zs = [v[2] for t in tris for v in t]
    places = {(round(v[0], 6), round(v[1], 6)) for t in tris for v in t}
    return {"triangles": len(tris), "locations": len(places), "area": sum(area2d(t) for t in tris),
            "z_min": min(zs), "z_max": max(zs)}


def auto_interval(z_min: float, z_max: float) -> float:
    """فاصله «گرد» برای حدود ۱۰ تا ۲۰ منحنی: ۱، ۲، ۵ ضرب در توان ده."""
    span = max(z_max - z_min, 1e-9)
    raw = span / 12
    p = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * p:
            return m * p
    return 10 * p


def contours(tris, interval: float, base: float = 0.0, index_every: int = 5) -> list[dict]:
    """
    مثلث‌های حاشیه‌ای (marching triangles). هر یال مشترک دقیقاً یک نقطه تقاطع دارد (کلید یال، نه مختصات)،
    پس قطعه‌ها بدون خطای گرد کردن به خط‌های پیوسته وصل می‌شوند. قاعده «z >= سطح بالاست» تساوی‌ها را یکدست می‌کند.
    خروجی: [{"level", "index", "coords": [(x, y)…], "closed"}]
    """
    if not interval or interval <= 0:
        raise SurfaceError("فاصله منحنی‌ها باید بزرگ‌تر از صفر باشد.")
    if not tris:
        return []
    zmin = min(v[2] for t in tris for v in t)
    zmax = max(v[2] for t in tris for v in t)
    k0, k1 = math.ceil((zmin - base) / interval - 1e-12), math.floor((zmax - base) / interval + 1e-12)
    if k1 - k0 + 1 > MAX_LEVELS:
        raise SurfaceError(f"با این فاصله بیش از {MAX_LEVELS} منحنی ساخته می‌شود؛ فاصله را بیشتر کنید.")

    vid: dict[tuple[float, float], int] = {}
    verts: list[tuple[float, float, float]] = []

    def vi(v):
        key = (round(v[0], 6), round(v[1], 6))
        if key not in vid:
            vid[key] = len(verts)
            verts.append(v)
        return vid[key]

    itris = [(vi(t[0]), vi(t[1]), vi(t[2])) for t in tris]
    out: list[dict] = []
    for k in range(k0, k1 + 1):
        level = base + k * interval
        pts: dict[tuple[int, int], tuple[float, float]] = {}
        adj: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for tri in itris:
            hi = [verts[i][2] >= level for i in tri]
            if all(hi) or not any(hi):
                continue
            keys = []
            for a in range(3):
                i, j = tri[a], tri[(a + 1) % 3]
                if hi[a] != hi[(a + 1) % 3]:
                    key = (i, j) if i < j else (j, i)
                    if key not in pts:
                        (x0, y0, z0), (x1, y1, z1) = verts[key[0]], verts[key[1]]
                        t = (level - z0) / (z1 - z0)
                        pts[key] = (x0 + t * (x1 - x0), y0 + t * (y1 - y0))
                    keys.append(key)
            a, b = keys
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
        out.extend(_chain(adj, pts, level, index_every and k % index_every == 0))
        if len(out) > MAX_FEATURES:
            raise SurfaceError("تعداد منحنی‌ها از حد مجاز بیشتر شد؛ فاصله را بیشتر کنید.")
    return out


def _chain(adj, pts, level, is_index):
    seen: set = set()
    lines = []

    def walk(start):
        path, prev, cur = [start], None, start
        seen.add(start)
        while True:
            nxt = [n for n in adj[cur] if n != prev and n not in seen]
            if not nxt:
                closed = start in adj[cur] and len(path) > 2 and prev is not None and start != prev
                return path, closed
            prev, cur = cur, nxt[0]
            seen.add(cur)
            path.append(cur)

    # ابتدا از انتهای خط‌های باز شروع می‌کنیم تا حلقه نصفه نشود
    for start in [k for k, v in adj.items() if len(v) == 1] + list(adj):
        if start in seen:
            continue
        path, closed = walk(start)
        coords = [pts[k] for k in path]
        if closed:
            coords.append(coords[0])
        lines.append({"level": level, "index": bool(is_index), "coords": coords, "closed": closed})
    return lines


def _one_vertex_positive(d0, d1, d2, area):
    """حجم بالای صفحه وقتی فقط رأس اول مثبت است (دو رأس دیگر منفی یا صفر)."""
    f1, f2 = d0 / (d0 - d1), d0 / (d0 - d2)
    return area * f1 * f2 * d0 / 3


def volume(tris, ref: float) -> dict:
    """حجم بین سطح TIN و صفحه افقی ارتفاع ref: cut = بالای صفحه (خاکبرداری)، fill = پایین صفحه (خاکریزی)."""
    cut = fill = 0.0
    for t in tris:
        a = area2d(t)
        d = [v[2] - ref for v in t]
        total = a * sum(d) / 3
        pos = sum(1 for x in d if x > 0)
        neg = sum(1 for x in d if x < 0)
        if neg == 0:
            c = total
        elif pos == 0:
            c = 0.0
        elif pos == 1:
            i = next(i for i, x in enumerate(d) if x > 0)
            c = _one_vertex_positive(d[i], d[(i + 1) % 3], d[(i + 2) % 3], a)
        else:  # دو رأس مثبت: بخش منفی فقط یک رأس دارد
            i = next(i for i, x in enumerate(d) if x < 0)
            neg_part = _one_vertex_positive(-d[i], -d[(i + 1) % 3], -d[(i + 2) % 3], a)
            c = total + neg_part
        cut += c
        fill += c - total
    return {"cut": cut, "fill": fill, "net": cut - fill}
