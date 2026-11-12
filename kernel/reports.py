"""گزارش PDF صفحه‌ی پلاگین (`[[reports]]`، ADR-0009 مرحله‌ی ۴، docs/plugins/reports.md).

- بلوک‌ها را همان `pagekit.render_block` می‌سازد (همان داده‌ی صفحه با همان فیلترها)؛ این ماژول فقط آن‌ها را به HTML چاپی
  و PDF (WeasyPrint) تبدیل می‌کند: هدر، تاریخ شمسی، شمارنده، جدول، نمودار میله‌ای و **نقشه‌ی برداری SVG** (مرکاتور، شبکه،
  مقیاس، فلش شمال؛ بدون نقشه‌ی پایه).
- امنیت: همه‌ی متن‌ها escape می‌شوند؛ **url_fetcher بسته** است (فقط دو فونت داخلی؛ هیچ منبع بیرونی یا فایل محلی واکشی نمی‌شود)؛
  سقف تعداد صفحه؛ پیام خطا ثابت و کوتاه است.
"""
from __future__ import annotations

import io
import math
import threading
from pathlib import Path

import jdatetime
from django.conf import settings
from django.utils import timezone
from django.utils.html import escape

MAX_PAGES = 40
MAP_W, MAP_H, MAP_PAD = 680, 360, 18
MAX_VERTICES = 60_000
FONT_URL = "https://fonts.report.invalid/vazirmatn-{w}.ttf"
FONT_FILES = {400: "vazirmatn-arabic-400-normal.woff2", 700: "vazirmatn-arabic-700-normal.woff2"}
_fonts: dict[int, bytes] = {}
_lock = threading.Lock()
_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


class ReportError(Exception):
    """پیام فارسی ثابت و کوتاه (بدون جزئیات داخلی)."""


def fa(v) -> str:
    return str(v).translate(_DIGITS)


def _font(weight: int) -> bytes:
    """فونت ووفِ۲ پروژه را یک‌بار به TTF تبدیل و نگه می‌دارد (FreeType/Fontconfig سازگارتر است)."""
    with _lock:
        if weight not in _fonts:
            from fontTools.ttLib import TTFont

            path = Path(settings.BASE_DIR) / "static" / "fonts" / FONT_FILES[weight]
            t = TTFont(str(path))
            t.flavor = None
            buf = io.BytesIO()
            t.save(buf)
            _fonts[weight] = buf.getvalue()
        return _fonts[weight]


# ---------------------------------------------------------------------- نقشه‌ی برداری
def _merc(lon: float, lat: float) -> tuple[float, float]:
    lat = max(min(lat, 85.05), -85.05)
    return lon, math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def _walk(geom, out: list):
    """مختصات‌ها را در فهرست تخت (نوع، داده) جمع می‌کند: ('pt', [x,y]) | ('line', [[x,y]…]) | ('poly', [[[x,y]…]…])."""
    if not isinstance(geom, dict):
        return
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Point":
        out.append(("pt", c))
    elif t == "MultiPoint":
        out.extend(("pt", p) for p in c)
    elif t == "LineString":
        out.append(("line", c))
    elif t == "MultiLineString":
        out.extend(("line", ln) for ln in c)
    elif t == "Polygon":
        out.append(("poly", c))
    elif t == "MultiPolygon":
        out.extend(("poly", p) for p in c)
    elif t == "GeometryCollection":
        for g in geom.get("geometries") or []:
            _walk(g, out)


def _nice(step: float) -> float:
    base = 10 ** math.floor(math.log10(step))
    for m in (1, 2, 5, 10):
        if m * base >= step:
            return m * base
    return 10 * base


def svg_map(geojson: dict, width: int = MAP_W, height: int = MAP_H) -> str:
    """FeatureCollection ← SVG (رشته‌ی امن: فقط عددهای محاسبه‌شده و متن escape‌شده)؛ خالی = ''."""
    items: list = []
    for f in (geojson or {}).get("features", [])[:2000]:
        _walk(f.get("geometry"), items)
    pts = []
    try:
        for kind, d in items:
            if kind == "pt":
                pts.append(_merc(float(d[0]), float(d[1])))
            elif kind == "line":
                pts.extend(_merc(float(p[0]), float(p[1])) for p in d)
            else:
                pts.extend(_merc(float(p[0]), float(p[1])) for ring in d for p in ring)
    except (TypeError, ValueError, IndexError):
        return ""
    if not pts:
        return ""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    dx, dy = max(maxx - minx, 0.004), max(maxy - miny, 0.004)
    s = min((width - 2 * MAP_PAD) / dx, (height - 2 * MAP_PAD) / dy)
    ox = (width - dx * s) / 2 - minx * s
    oy = (height - dy * s) / 2 + maxy * s

    def px(lon, lat):
        x, y = _merc(float(lon), float(lat))
        return round(x * s + ox, 1), round(oy - y * s, 1)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img">',
           f'<rect width="{width}" height="{height}" fill="#F6F4EE" stroke="#CFCABB"/>']
    # شبکه (طول و عرض جغرافیایی)
    step = _nice(max(dx, dy * 1.0) / 4)
    lon0 = math.ceil((minx - MAP_PAD / s) / step) * step
    lon = lon0
    while lon <= maxx + MAP_PAD / s and lon0 + 40 * step > lon:
        x = round(lon * s + ox, 1)
        if 0 < x < width:
            out.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{height}" stroke="#DDD8C8" stroke-width="0.6"/>'
                       f'<text x="{x + 2}" y="{height - 4}" font-size="8" fill="#7A7566">{escape(fa(round(lon, 4)))}</text>')
        lon += step
    lat_min = math.degrees(2 * math.atan(math.exp(math.radians(miny - MAP_PAD / s))) - math.pi / 2)
    lat = math.ceil(lat_min / step) * step
    for _ in range(40):
        _x, y = _merc(0, lat)
        yy = round(oy - y * s, 1)
        if yy < 0:
            break
        if yy < height:
            out.append(f'<line x1="0" y1="{yy}" x2="{width}" y2="{yy}" stroke="#DDD8C8" stroke-width="0.6"/>'
                       f'<text x="3" y="{yy - 2}" font-size="8" fill="#7A7566">{escape(fa(round(lat, 4)))}</text>')
        lat += step
    # هندسه‌ها
    budget = MAX_VERTICES
    for kind, d in items:
        if budget <= 0:
            break
        if kind == "poly":
            path = []
            for ring in d:
                pp = [px(p[0], p[1]) for p in ring][:budget]
                budget -= len(pp)
                path.append("M" + " L".join(f"{x} {y}" for x, y in pp) + "Z")
            out.append(f'<path d="{" ".join(path)}" fill="#E0A526" fill-opacity="0.35" stroke="#0F5C59" stroke-width="1.2" fill-rule="evenodd"/>')
        elif kind == "line":
            pp = [px(p[0], p[1]) for p in d][:budget]
            budget -= len(pp)
            out.append(f'<polyline points="{" ".join(f"{x},{y}" for x, y in pp)}" fill="none" stroke="#0F5C59" stroke-width="1.6"/>')
        else:
            x, y = px(d[0], d[1])
            budget -= 1
            out.append(f'<circle cx="{x}" cy="{y}" r="3.2" fill="#E0A526" stroke="#0F5C59" stroke-width="1"/>')
    # مقیاس
    latc = (miny + maxy) / 2
    latc = math.degrees(2 * math.atan(math.exp(math.radians(latc))) - math.pi / 2)
    m_per_px = 111_320 * math.cos(math.radians(latc)) / s
    length_m = _nice(m_per_px * 90)
    bar = round(length_m / m_per_px, 1)
    km = length_m >= 1000
    num = f"{(length_m / 1000 if km else length_m):g}".replace(".", "٫")
    label = f"{fa(num)} {'کیلومتر' if km else 'متر'}"
    out.append(f'<g transform="translate(14,{height - 22})"><line x1="0" y1="0" x2="{bar}" y2="0" stroke="#1F2933" stroke-width="2"/>'
               f'<line x1="0" y1="-4" x2="0" y2="4" stroke="#1F2933"/><line x1="{bar}" y1="-4" x2="{bar}" y2="4" stroke="#1F2933"/>'
               f'<text x="0" y="-7" font-size="9" fill="#1F2933">{escape(label)}</text></g>')
    out.append(f'<g transform="translate({width - 26},26)"><path d="M0 -14 L7 8 L0 3 L-7 8 Z" fill="#1F2933"/>'
               f'<text x="0" y="22" font-size="10" text-anchor="middle" fill="#1F2933">ش</text></g>')
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------- HTML
CSS = """
@page { size: %(size)s; margin: 16mm 14mm 18mm; @bottom-center { content: counter(page, persian) " / " counter(pages, persian); font: 9pt Vazirmatn; color: #7A7566 } }
* { box-sizing: border-box }
body { font-family: Vazirmatn, sans-serif; font-size: 10pt; color: #1F2933; line-height: 1.7; direction: rtl }
h1 { font-size: 18pt; margin: 0 0 2pt; color: #0F5C59 }
.sub { color: #7A7566; margin: 0 0 4pt }
.meta { display: flex; justify-content: space-between; border-bottom: 1.5pt solid #0F5C59; padding-bottom: 6pt; margin-bottom: 10pt; font-size: 9pt; color: #52606D }
h2 { font-size: 12pt; margin: 14pt 0 5pt; color: #0F5C59; break-after: avoid }
.kpis { display: flex; flex-wrap: wrap; gap: 8pt; margin-bottom: 6pt }
.kpi { flex: 1 1 28%%; border: 0.8pt solid #CFCABB; border-radius: 4pt; padding: 6pt 8pt; break-inside: avoid }
.kpi b { display: block; font-size: 16pt; color: #0F5C59 }
.kpi small { color: #7A7566 }
table { width: 100%%; border-collapse: collapse; font-size: 9pt; margin-bottom: 4pt }
th { background: #0F5C59; color: #fff; text-align: right; padding: 3pt 5pt; font-weight: 700 }
td { padding: 3pt 5pt; border-bottom: 0.5pt solid #DDD8C8 }
thead { display: table-header-group } tr { break-inside: avoid }
.bars { list-style: none; margin: 0; padding: 0 }
.bars li { display: flex; align-items: center; gap: 6pt; margin: 2pt 0; break-inside: avoid }
.bl { width: 28%% } .bt { flex: 1; height: 8pt; background: #EFEBDD; border-radius: 4pt } .bt i { display: block; height: 100%%; background: #E0A526; border-radius: 4pt }
.bv { width: 14%%; text-align: left; direction: ltr }
.map svg { width: 100%%; height: auto; display: block; break-inside: avoid }
.note, .err { color: #7A7566; font-size: 9pt } .err { color: #B3261E }
"""


def _cell(v) -> str:
    return escape(fa(v)) if v is not None else "—"


def build_html(*, report, page_title: str, blocks: list[dict], site_name: str, db_label: str, filters: list[str], now) -> str:
    j = jdatetime.datetime.fromgregorian(datetime=timezone.localtime(now)).strftime("%Y/%m/%d %H:%M")
    head = [f'<h1>{escape(report.title)}</h1>']
    if report.subtitle:
        head.append(f'<p class="sub">{escape(report.subtitle)}</p>')
    meta = (f'<div class="meta"><span>{escape(site_name)} · {escape(page_title)} · پایگاه «{escape(db_label)}»</span>'
            f'<span>تاریخ گزارش: {escape(fa(j))}</span></div>')
    body = []
    kpis = [b for b in blocks if b["kind"] == "kpi"]
    if kpis:
        cells = "".join(f'<div class="kpi">{("<small>" + escape(b["error"]) + "</small>") if b.get("error") else "<b>" + escape(fa(b["value"])) + (" <small>" + escape(b.get("unit", "")) + "</small>" if b.get("unit") else "") + "</b>"}<small>{escape(b["title"])}</small></div>' for b in kpis)
        body.append(f'<div class="kpis">{cells}</div>')
    for b in blocks:
        if b["kind"] == "kpi":
            continue
        if b.get("title"):
            body.append(f'<h2>{escape(b["title"])}</h2>')
        if b.get("error"):
            body.append(f'<p class="err">{escape(b["error"])}</p>')
        elif b["kind"] == "text":
            body.extend(f'<p>{escape(p)}</p>' for p in b.get("paras", []))
        elif b["kind"] == "table":
            if b.get("rows"):
                th = "".join(f"<th>{escape(h)}</th>" for h in b["headers"])
                tr = "".join("<tr>" + "".join(f"<td>{_cell(c)}</td>" for c in r) + "</tr>" for r in b["rows"])
                body.append(f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>")
                if b.get("truncated"):
                    body.append('<p class="note">فقط ۲۰۰ ردیف اول آمده است.</p>')
            else:
                body.append('<p class="note">داده‌ای برای نمایش نیست.</p>')
        elif b["kind"] == "bars":
            if b.get("bars"):
                li = "".join(f'<li><span class="bl">{escape(x["label"])}</span><span class="bt"><i style="width:{int(x["pct"])}%"></i></span><span class="bv">{escape(fa(x["value"]))}</span></li>' for x in b["bars"])
                body.append(f'<ul class="bars">{li}</ul>')
            else:
                body.append('<p class="note">داده‌ای برای نمایش نیست.</p>')
        elif b["kind"] == "map":
            svg = svg_map(b.get("geojson") or {})
            body.append(f'<div class="map">{svg}</div><p class="note">نقشه‌ی برداری بدون نقشه‌ی پایه؛ {escape(fa(b.get("count", 0)))} عارضه.</p>' if svg
                        else '<p class="note">داده‌ی مکانی برای نقشه نیست.</p>')
    flt = f'<p class="note">فیلترها: {escape("؛ ".join(filters))}</p>' if filters else ""
    css = CSS % {"size": "A4 landscape" if report.landscape else "A4"}
    return (f'<!doctype html><html dir="rtl" lang="fa"><head><meta charset="utf-8"><title>{escape(report.title)}</title><style>'
            f'@font-face{{font-family:Vazirmatn;font-weight:400;src:url({FONT_URL.format(w=400)})}}'
            f'@font-face{{font-family:Vazirmatn;font-weight:700;src:url({FONT_URL.format(w=700)})}}{css}</style></head><body>'
            f'{"".join(head)}{meta}{flt}{"".join(body)}</body></html>')


# ---------------------------------------------------------------------- PDF
def _font_for(url: str) -> bytes:
    for w in FONT_FILES:
        if url == FONT_URL.format(w=w):
            return _font(w)
    raise ValueError("blocked")


def _fetcher(url, *args, **kwargs):
    """واکشی‌کننده‌ی بسته (تابع؛ WeasyPrint قدیمی): فقط دو فونت داخلی، هر نشانی دیگر رد می‌شود."""
    return {"string": _font_for(url), "mime_type": "font/ttf"}


def make_fetcher():
    """فقط دو فونت داخلی؛ هر نشانی دیگر (شبکه، فایل محلی، data) رد می‌شود. WeasyPrint ≥ ۶۸: زیرکلاس URLFetcher."""
    try:
        from weasyprint.urls import URLFetcher, URLFetcherResponse
    except ImportError:  # pragma: no cover - نسخه‌ی قدیمی
        return _fetcher

    class ClosedFetcher(URLFetcher):
        def fetch(self, url, headers=None):
            return URLFetcherResponse(url, body=_font_for(url), headers={"Content-Type": "font/ttf"})

    return ClosedFetcher(allowed_protocols=())


def to_pdf(html: str, title: str = "") -> bytes:
    try:
        from weasyprint import HTML
    except Exception as exc:  # noqa: BLE001 - کتابخانه‌ی سیستمی (pango) نصب نیست
        raise ReportError("ساخت PDF روی این سرور آماده نیست.") from exc
    try:
        doc = HTML(string=html, url_fetcher=make_fetcher()).render()
        if len(doc.pages) > MAX_PAGES:
            raise ReportError(f"گزارش بیش از {MAX_PAGES} صفحه می‌شود؛ فیلتر را محدودتر کنید.")
        return doc.write_pdf()
    except ReportError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ReportError("ساخت PDF انجام نشد.") from exc
