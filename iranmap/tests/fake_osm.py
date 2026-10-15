"""
فایل OSM ساختگی «شهر نمونه» (هندسه همان نقشه پایه ساختگی ویدیوها) برای آزمون و ضبط ویدیوی داده آماده ایران.
داده واقعی OSM از این محیط در دسترس نیست؛ روی سرور اصلی، فایل ایران از Geofabrik دانلود می‌شود.
خروجی: XML نسخه 0.6 که osmium به pbf تبدیل می‌کند.
"""
import math
import sys
from xml.sax.saxutils import quoteattr

import numpy as np
from scipy.spatial import Voronoi

rng = np.random.default_rng(3)
W, S, E, N = 51.12, 35.50, 51.68, 35.88
out = open(sys.argv[1], "w", encoding="utf-8")
nid, wid, rid = [0], [0], [0]
nodes, ways, rels = [], [], []
STREET = ["ولیعصر", "آزادی", "انقلاب", "شریعتی", "مطهری", "طالقانی", "کارگر", "جمهوری", "فاطمی", "بهشتی",
          "حافظ", "سعدی", "فردوسی", "مولوی", "نواب", "یادگار امام", "ستارخان", "پاسداران", "دماوند", "پیروزی",
          "گلستان", "نارنجستان", "لاله", "یاس", "نسترن", "مریم", "بهار", "سپیده", "آفتاب", "مهتاب"]
HWY = [("بزرگراه همت", "motorway"), ("بزرگراه مدرس", "motorway"), ("بزرگراه حکیم", "trunk"),
       ("بزرگراه نیایش", "trunk"), ("بزرگراه امام علی", "motorway")]
POI = [("school", "مدرسه"), ("hospital", "بیمارستان"), ("pharmacy", "داروخانه"), ("bank", "بانک"),
       ("restaurant", "رستوران"), ("cafe", "کافه"), ("fuel", "جایگاه سوخت"), ("place_of_worship", "مسجد"),
       ("library", "کتابخانه"), ("clinic", "درمانگاه")]


def node(lon, lat, tags=None):
    nid[0] += 1
    nodes.append((nid[0], lon, lat, tags or {}))
    return nid[0]


def way(refs, tags):
    wid[0] += 1
    ways.append((wid[0], refs, tags))
    return wid[0]


# تقاطع‌ها مشترک باشند (برای شبکه مسیریابی)
pts = []
while len(pts) < 2600:
    lon, lat = rng.uniform(W, E), rng.uniform(S, N)
    d = math.hypot((lon - 51.40) / 0.25, (lat - 35.70) / 0.17)
    if rng.random() < math.exp(-d * d * 0.9):
        pts.append((lon, lat))
vor = Voronoi(np.array(pts))
vnode = {}


def vn(i):
    if i not in vnode:
        x, y = vor.vertices[i]
        vnode[i] = node(float(x), float(y))
    return vnode[i]


for k, (a, b) in enumerate(vor.ridge_vertices):
    if a < 0 or b < 0:
        continue
    pa, pb = vor.vertices[a], vor.vertices[b]
    if not (W < pa[0] < E and S < pa[1] < N and W < pb[0] < E and S < pb[1] < N):
        continue
    if math.dist(pa, pb) > 0.03:
        continue
    kind = "secondary" if k % 11 == 0 else ("tertiary" if k % 5 == 0 else "residential")
    name = ("خیابان " if kind != "residential" else "کوچه ") + STREET[k % len(STREET)] + (f" {k % 17 + 1}" if kind == "residential" else "")
    tags = {"highway": kind, "name": name, "name:fa": name}
    if kind == "residential" and k % 7 == 0:
        tags["oneway"] = "yes"
    tags["maxspeed"] = {"secondary": "60", "tertiary": "50", "residential": "30"}[kind]
    way([vn(a), vn(b)], tags)

majors = [
    [(51.13, 35.72), (51.25, 35.73), (51.33, 35.705), (51.42, 35.70), (51.52, 35.705), (51.67, 35.69)],
    [(51.39, 35.52), (51.395, 35.60), (51.41, 35.68), (51.42, 35.76), (51.43, 35.87)],
    [(51.20, 35.60), (51.30, 35.65), (51.38, 35.73), (51.48, 35.80), (51.60, 35.85)],
    [(51.25, 35.82), (51.33, 35.77), (51.47, 35.66), (51.58, 35.60)],
    [(51.28, 35.56), (51.36, 35.60), (51.50, 35.62), (51.64, 35.64)],
]
for (name, kind), line in zip(HWY, majors, strict=False):
    way([node(*p) for p in line], {"highway": kind, "name": name, "name:fa": name, "maxspeed": "100", "oneway": "no"})

river = [(51.12, 35.64), (51.22, 35.655), (51.30, 35.64), (51.36, 35.615), (51.46, 35.60), (51.55, 35.575), (51.68, 35.56)]
way([node(*p) for p in river], {"waterway": "river", "name": "رود کن", "name:fa": "رود کن"})

for i in range(70):
    c = (rng.uniform(W + .03, E - .03), rng.uniform(S + .02, N - .02))
    r = rng.uniform(.003, .012)
    k = rng.integers(5, 9)
    ang = np.sort(rng.uniform(0, 2 * np.pi, k))
    ring = [node(c[0] + r * math.cos(a) * rng.uniform(.6, 1.2), c[1] + r * .8 * math.sin(a) * rng.uniform(.6, 1.2)) for a in ang]
    name = f"پارک {STREET[i % len(STREET)]}"
    way(ring + [ring[0]], {"leisure": "park", "name": name, "name:fa": name})

# ساختمان‌ها: مستطیل‌های کوچک کنار مرکز
for i in range(1800):
    lon = float(rng.normal(51.40, 0.06))
    lat = float(rng.normal(35.70, 0.04))
    if not (W < lon < E and S < lat < N):
        continue
    w, h = rng.uniform(0.00015, 0.0004), rng.uniform(0.00012, 0.0003)
    ring = [node(lon, lat), node(lon + w, lat), node(lon + w, lat + h), node(lon, lat + h)]
    way(ring + [ring[0]], {"building": "yes" if i % 4 else "apartments", "building:levels": str(int(rng.integers(1, 12)))})

for i in range(600):
    lon = float(rng.normal(51.40, 0.07))
    lat = float(rng.normal(35.70, 0.05))
    if not (W < lon < E and S < lat < N):
        continue
    amenity, fa = POI[i % len(POI)]
    name = f"{fa} {STREET[(i * 7) % len(STREET)]}"
    node(lon, lat, {"amenity": amenity, "name": name, "name:fa": name})

for name, lon, lat, kind, pop in (("شهر نمونه", 51.40, 35.70, "city", "8700000"), ("ونک", 51.41, 35.76, "suburb", ""),
                                  ("تجریش", 51.43, 35.80, "suburb", ""), ("نارمک", 51.50, 35.74, "suburb", ""),
                                  ("صادقیه", 51.33, 35.72, "suburb", ""), ("شوش", 51.42, 35.66, "suburb", "")):
    tags = {"place": kind, "name": name, "name:fa": name}
    if pop:
        tags["population"] = pop
    node(lon, lat, tags)

# مرز شهر (relation مرز اداری سطح ۸)
ring = [node(51.16, 35.56), node(51.64, 35.56), node(51.64, 35.84), node(51.16, 35.84)]
b = way(ring + [ring[0]], {})
rid[0] += 1
rels.append((rid[0], [("way", b, "outer")], {"type": "boundary", "boundary": "administrative", "admin_level": "8",
                                              "name": "شهر نمونه", "name:fa": "شهر نمونه"}))
# استان (۴) و شهرستان (۵) نمونه
for lvl, name, box in (("4", "استان نمونه", (51.12, 35.50, 51.68, 35.88)), ("5", "شهرستان نمونه", (51.14, 35.53, 51.66, 35.86))):
    w0, s0, e0, n0 = box
    ring = [node(w0, s0), node(e0, s0), node(e0, n0), node(w0, n0)]
    b = way(ring + [ring[0]], {})
    rid[0] += 1
    rels.append((rid[0], [("way", b, "outer")], {"type": "boundary", "boundary": "administrative", "admin_level": lvl,
                                                  "name": name, "name:fa": name, "name:en": "Sample"}))

out.write("<?xml version='1.0' encoding='UTF-8'?>\n<osm version=\"0.6\" generator=\"fake_osm\">\n")
out.write(f'  <bounds minlat="{S}" minlon="{W}" maxlat="{N}" maxlon="{E}"/>\n')


def tagxml(tags):
    return "".join(f"    <tag k={quoteattr(k)} v={quoteattr(v)}/>\n" for k, v in tags.items())


for i, lon, lat, tags in nodes:
    attrs = f'id="{i}" version="1" timestamp="2026-10-01T00:00:00Z" lat="{lat:.7f}" lon="{lon:.7f}"'
    out.write(f"  <node {attrs}>\n{tagxml(tags)}  </node>\n" if tags else f"  <node {attrs}/>\n")
for i, refs, tags in ways:
    out.write(f'  <way id="{i}" version="1" timestamp="2026-10-01T00:00:00Z">\n')
    out.write("".join(f'    <nd ref="{r}"/>\n' for r in refs) + tagxml(tags) + "  </way>\n")
for i, members, tags in rels:
    out.write(f'  <relation id="{i}" version="1" timestamp="2026-10-01T00:00:00Z">\n')
    out.write("".join(f'    <member type="{t}" ref="{r}" role="{role}"/>\n' for t, r, role in members))
    out.write(tagxml(tags) + "  </relation>\n")
out.write("</osm>\n")
print(len(nodes), "nodes", len(ways), "ways")
