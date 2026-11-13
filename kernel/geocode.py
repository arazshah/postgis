"""ژئوکدر فارسی آزمایشی (ADR-0009 مرحله‌ی ۵): نشانی متنی ← مختصات + درجه‌ی اطمینان، روی «داده آماده ایران» همان پایگاه.

منبع: جدول‌های `osm_roads`، `osm_pois`، `osm_places` که مشتری از OpenStreetMap به پایگاه خودش آورده (iranmap). OSM **پلاک و کدپستی ندارد**؛
پس دقت نهایی «روی معبر / نام مکان / محله / شهر» است نه «در خانه». پلاک خوانده می‌شود ولی در یافتن نقطه نقشی ندارد (در `note`).

- بارگذاری فقط‌خواندنی و محدود به شعاع شهر انتخابی (نام معبر در شهرهای مختلف تکراری است).
- تطبیق در پایتون: نرمال‌سازی فارسی، هسته‌ی نام (بدون نوع معبر و عنوان‌ها)، برابری، زیرمجموعه‌ی واژه‌ها و فاصله‌ی ویرایشی.
- مبهم بودن (چند معبر هم‌امتیاز) امتیاز را می‌کاهد و گزارش می‌شود؛ هیچ‌وقت حدس بی‌نشانه نمی‌دهد.
"""
from __future__ import annotations

import difflib
import math
from dataclasses import dataclass, field

from psycopg import sql

from . import persian, tenantdb

TABLES = ("osm_roads", "osm_pois", "osm_places")
MAX_NAMES, STMT = 120_000, "20s"
FUZZY_CUTOFF = 0.84
LEVELS = {"street": "معبر", "poi": "مکان", "neighbourhood": "محله", "city": "شهر", "none": "نامعلوم"}
NEIGHBOURHOOD_KINDS = {"suburb", "neighbourhood", "quarter", "village", "hamlet", "locality", "borough"}
CITY_KINDS = {"city", "town"}


class GeocodeError(Exception):
    """پیام فارسی ثابت برای مدیر/کاربر."""


@dataclass(frozen=True)
class Entry:
    name: str
    norm: str
    core: str
    tokens: frozenset
    lon: float
    lat: float
    n: int = 1
    kind: str = ""
    pop: int = 0


@dataclass
class Gazetteer:
    streets: list[Entry] = field(default_factory=list)
    pois: list[Entry] = field(default_factory=list)
    hoods: list[Entry] = field(default_factory=list)
    cities: list[Entry] = field(default_factory=list)
    center: tuple[float, float] | None = None
    city_name: str = ""

    def __post_init__(self):
        self._cache: dict[int, tuple] = {}

    def _prep(self, entries: list[Entry]):
        k = id(entries)
        if k not in self._cache:
            self._cache[k] = (entries, [e.core for e in entries])
        return self._cache[k]


@dataclass
class Result:
    text: str
    level: str = "none"
    score: float = 0.0
    lon: float | None = None
    lat: float | None = None
    matched: str = ""
    note: str = ""
    ambiguous: bool = False

    @property
    def level_label(self) -> str:
        return LEVELS[self.level]

    @property
    def label(self) -> str:
        return "بالا" if self.score >= 0.85 else "متوسط" if self.score >= 0.6 else "پایین" if self.score > 0 else "—"


def entry(name: str, lon: float, lat: float, *, n: int = 1, kind: str = "", pop: int = 0) -> Entry | None:
    norm = persian.normalize(name)
    if not norm:
        return None
    return Entry(name, norm, persian.core(name), frozenset(persian.core(name).split()), float(lon), float(lat), n, kind, pop)


# ---------------------------------------------------------------------- بارگذاری از پایگاه مشتری
def _have_tables(ws) -> set[str]:
    return {t.name for t in tenantdb.catalog(ws).tables() if t.schema == "public"} & set(TABLES)


def cities(ws) -> list[Entry]:
    """شهرها و شهرک‌های «osm_places» (برای انتخاب مرکز و تشخیص شهر دیگر در نشانی)."""
    if "osm_places" not in _have_tables(ws):
        raise GeocodeError("جدول osm_places در این پایگاه نیست؛ اول «داده آماده ایران» را برای شهر به پایگاه بیاورید.")
    q = sql.SQL("""SELECT name, place, ST_X(ST_PointOnSurface(geom)), ST_Y(ST_PointOnSurface(geom)),
                          COALESCE(NULLIF(regexp_replace(population, '[^0-9]', '', 'g'), '')::bigint, 0)
                   FROM osm_places WHERE name IS NOT NULL AND place = ANY(%s) ORDER BY 5 DESC LIMIT 2000""")
    out = []
    with tenantdb.connect(ws) as conn:
        conn.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(STMT)))
        for name, kind, x, y, pop in conn.execute(q, (sorted(CITY_KINDS),)).fetchall():
            e = entry(name, x, y, kind=kind, pop=int(pop or 0))
            if e:
                out.append(e)
    return out


def load(ws, city: str, radius_km: float = 15.0) -> Gazetteer:
    """گازتیر یک شهر: شهر با نام (نرمال‌شده) از osm_places پیدا می‌شود و معبرها/مکان‌ها/محله‌های شعاع آن بار می‌شوند."""
    have = _have_tables(ws)
    if "osm_roads" not in have:
        raise GeocodeError("جدول osm_roads در این پایگاه نیست؛ «داده آماده ایران» را (دسته‌ی معابر) بیاورید.")
    all_cities = cities(ws)
    want = persian.core(city)
    center = next((c for c in all_cities if c.core == want), None) or next((c for c in all_cities if want and want in c.tokens), None)
    if center is None:
        raise GeocodeError(f"شهر «{city}» در osm_places پیدا نشد.")
    r_m = max(1.0, min(float(radius_km), 60.0)) * 1000
    gz = Gazetteer(cities=all_cities, center=(center.lon, center.lat), city_name=center.name)
    pt = sql.SQL("ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography")
    with tenantdb.connect(ws) as conn:
        conn.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(STMT)))
        roads = conn.execute(sql.SQL("""
            SELECT name, ST_X(p), ST_Y(p), n FROM (
              SELECT name, count(*) AS n, ST_ClosestPoint(ST_Collect(geom), ST_Centroid(ST_Collect(geom))) AS p
              FROM osm_roads WHERE name IS NOT NULL AND ST_DWithin(geom::geography, {pt}, %s) GROUP BY name) s LIMIT %s""").format(pt=pt),
            (center.lon, center.lat, r_m, MAX_NAMES)).fetchall()
        for name, x, y, n in roads:
            e = entry(name, x, y, n=int(n))
            if e:
                gz.streets.append(e)
        if "osm_pois" in have:
            for name, x, y in conn.execute(sql.SQL("""SELECT name, ST_X(ST_PointOnSurface(geom)), ST_Y(ST_PointOnSurface(geom)) FROM osm_pois
                   WHERE name IS NOT NULL AND ST_DWithin(geom::geography, {pt}, %s) LIMIT %s""").format(pt=pt), (center.lon, center.lat, r_m, MAX_NAMES)):
                e = entry(name, x, y)
                if e:
                    gz.pois.append(e)
        if "osm_places" in have:
            for name, kind, x, y in conn.execute(sql.SQL("""SELECT name, place, ST_X(ST_PointOnSurface(geom)), ST_Y(ST_PointOnSurface(geom)) FROM osm_places
                   WHERE name IS NOT NULL AND place = ANY(%s) AND ST_DWithin(geom::geography, {pt}, %s) LIMIT %s""").format(pt=pt),
                                          (sorted(NEIGHBOURHOOD_KINDS), center.lon, center.lat, r_m, MAX_NAMES)):
                e = entry(name, x, y, kind=kind)
                if e:
                    gz.hoods.append(e)
    return gz


# ---------------------------------------------------------------------- تطبیق
def name_score(q_norm: str, q_core: str, q_tokens: frozenset, c: Entry) -> float:
    """شباهت نام جست‌وجو و نامزد: ۰ تا ۱ (فقط برای نامزدهای هم‌واژه یا نزدیک؛ بقیه صفر)."""
    if not q_core or not c.core:
        return 0.0
    if q_norm == c.norm:
        return 0.95
    if q_core == c.core:
        return 0.92
    qs, cs = q_core.replace(" ", ""), c.core.replace(" ", "")
    if qs == cs and len(qs) >= 3:  # فقط فاصله فرق دارد («ولی عصر» / «ولیعصر»)
        return 0.9
    if len(q_core) >= 3 and q_tokens and q_tokens <= c.tokens:
        return max(0.7, 0.84 - 0.02 * max(0, len(c.tokens) - len(q_tokens) - 1))
    if len(c.core) >= 3 and c.tokens and c.tokens <= q_tokens:
        return 0.78
    ratio = difflib.SequenceMatcher(None, qs, cs).ratio()
    return round(0.75 * ratio, 3) if ratio >= FUZZY_CUTOFF else 0.0


def _best(gz: Gazetteer, entries: list[Entry], text: str, *, min_score: float):
    """(بهترین، امتیاز، مبهم؟). ابهام: دو نامزد با نام متفاوت و امتیاز تقریباً برابر."""
    q_norm, q_core = persian.normalize(text), persian.core(text)
    q_tokens = frozenset(q_core.split())
    if not q_core:
        return None, 0.0, False
    scored = []
    cands = entries
    if len(entries) > 3000:  # هرس: فقط نامزدهایی که یک واژه‌ی مشترک دارند یا نزدیک‌اند
        _e, cores = gz._prep(entries)
        near = set(difflib.get_close_matches(q_core, cores, n=8, cutoff=FUZZY_CUTOFF))
        cands = [e for e in entries if e.tokens & q_tokens or e.core in near]
    for c in cands:
        s = name_score(q_norm, q_core, q_tokens, c)
        if s >= min_score:
            scored.append((s, c.n, c))
    if not scored:
        return None, 0.0, False
    scored.sort(key=lambda t: (-t[0], -t[1]))
    s, _n, top = scored[0]
    amb = any(o[2].core != top.core and abs(o[0] - s) < 0.02 for o in scored[1:])
    return top, s, amb


def _hav_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    (x1, y1), (x2, y2) = a, b
    p1, p2 = math.radians(y1), math.radians(y2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(x2 - x1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def geocode(gz: Gazetteer, text: str) -> Result:
    res = Result(text=text)
    a = persian.parse_address(text)
    parts = a["parts"]
    if not parts:
        res.note = "نشانی خالی است."
        return res
    notes = []
    if a["number"]:
        notes.append(f"پلاک {persian.normalize(a['number'])} در نقشه‌ی OSM نیست؛ نقطه روی معبر است")
    # شهر دیگری در نشانی؟
    here = persian.core(gz.city_name)
    other = None
    for p in parts:
        pc = persian.core(p)
        if pc and pc != here and not persian.street_type(p):
            hit = next((c for c in gz.cities if c.core == pc and c.core != here), None)
            if hit:
                other = hit
    street_part = a["street"]
    cands = [street_part] if street_part else []
    cands += [p for p in parts if p != street_part]
    if other is not None and not street_part:
        res.level, res.score, res.lon, res.lat, res.matched = "city", 0.4, other.lon, other.lat, other.name
        res.note = "؛ ".join([*notes, "شهر دیگری در نشانی آمده؛ فقط مرکز شهر"])
        return res
    # ۱) معبر
    best = (None, 0.0, False, "")
    for p in cands:
        e, s, amb = _best(gz, gz.streets, p, min_score=0.65)
        if e and s > best[1] and (p == street_part or persian.street_type(p) or s >= 0.9 or (len(parts) == 1 and s >= 0.7)):
            best = (e, s, amb, "street")
    if best[0] is not None:
        e, s, amb, _k = best
        if amb:
            s = max(0.0, s - 0.1)
            notes.append("چند معبر با نام مشابه هست؛ پرتکرارترین انتخاب شد")
        res.level, res.score, res.lon, res.lat, res.matched, res.ambiguous = "street", round(s, 3), e.lon, e.lat, e.name, amb
        res.note = "؛ ".join(notes)
        if other is not None:
            res.note += "؛ شهر دیگری هم در نشانی آمده؛ بررسی کنید"
            res.score = min(res.score, 0.5)
        return res
    # ۲) مکان (POI) و ۳) محله
    for kind, entries, floor, top in (("poi", gz.pois, 0.78, 0.8), ("neighbourhood", gz.hoods, 0.78, 0.6)):
        sbest = (None, 0.0, False)
        for p in parts:
            e, s, amb = _best(gz, entries, p, min_score=floor)
            if e and s > sbest[1]:
                sbest = (e, s, amb)
        if sbest[0] is not None:
            e, s, amb = sbest
            res.level, res.score, res.lon, res.lat, res.matched, res.ambiguous = kind, round(min(s, top) - (0.1 if amb else 0), 3), e.lon, e.lat, e.name, amb
            res.note = "؛ ".join(notes)
            return res
    # ۴) فقط شهر
    for p in parts:
        pc = persian.core(p)
        hit = next((c for c in gz.cities if pc and c.core == pc), None)
        if hit:
            res.level, res.score, res.lon, res.lat, res.matched = "city", 0.4, hit.lon, hit.lat, hit.name
            res.note = "؛ ".join([*notes, "فقط شهر پیدا شد (مرکز شهر)"])
            return res
    res.note = "؛ ".join([*notes, "نام معبر/مکانی تطبیق نکرد"])
    return res


def geocode_many(gz: Gazetteer, lines: list[str]) -> list[Result]:
    return [geocode(gz, t) for t in lines]


def stats(results: list[Result]) -> dict:
    """خلاصه‌ی کیفیت برای ارزیابی: نرخ تطبیق (امتیاز ≥ ۰٫۶)، سطح‌ها و ابهام."""
    n = len(results) or 1
    good = [r for r in results if r.score >= 0.6]
    by = {k: sum(1 for r in results if r.level == k) for k in LEVELS}
    return {"total": len(results), "matched": len(good), "rate": round(100 * len(good) / n, 1),
            "high": sum(1 for r in results if r.score >= 0.85), "mid": sum(1 for r in results if 0.6 <= r.score < 0.85),
            "low": sum(1 for r in results if 0 < r.score < 0.6), "none": sum(1 for r in results if r.level == "none"),
            "street_rate": round(100 * by["street"] / n, 1), "ambiguous": sum(1 for r in results if r.ambiguous), "levels": by}


def safe_cell(v) -> str:
    """جلوگیری از تزریق فرمول در اکسل (ورودی کاربر)."""
    v = str(v or "")
    return "'" + v if v[:1] in "=+-@\t\r" else v


def results_csv(results: list[Result]) -> str:
    """نتیجه ← متن CSV (با BOM برای اکسل فارسی)."""
    import csv
    import io

    out = io.StringIO()
    out.write("\ufeff")
    w = csv.writer(out)
    w.writerow(["نشانی", "سطح", "اطمینان", "امتیاز", "طول", "عرض", "نام تطبیق‌خورده", "توضیح"])
    for r in results:
        w.writerow([safe_cell(r.text), LEVELS[r.level], r.label, r.score, r.lon if r.lon is not None else "", r.lat if r.lat is not None else "",
                    safe_cell(r.matched), safe_cell(r.note)])
    return out.getvalue()


def lines_from_upload(data: bytes, column: str = "") -> list[str]:
    """فایل CSV/متن (UTF-8) ← فهرست نشانی. ستون: نام داده‌شده، یا «address/نشانی/آدرس» در سرستون، وگرنه ستون اول."""
    import csv
    import io

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise GeocodeError("فایل باید UTF-8 باشد.") from None
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if not rows:
        return []
    head = [h.strip().lower() for h in rows[0]]
    idx = 0
    for cand in ([column.strip().lower()] if column.strip() else []) + ["address", "نشانی", "آدرس", "addr"]:
        if cand in head:
            idx = head.index(cand)
            rows = rows[1:]
            break
    return [r[idx].strip() for r in rows if len(r) > idx and r[idx].strip()]
