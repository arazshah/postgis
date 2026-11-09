"""جلد کتاب: رو، پشت و گسترده‌ی کامل برای چاپخانه (پشت | عطف | رو؛ کتاب راست‌به‌چپ، پس جلد رو سمت راست است)."""
from __future__ import annotations

import html
import math
import random

W, H = 170, 240          # قطع وزیری (میلی‌متر)
BLEED = 3                # حاشیه‌ی برش


def fa(x) -> str:
    return str(x).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def spine_mm(pages: int) -> float:
    """کاغذ تحریر ۷۰ گرمی: حدود ۰٫۰۹ میلی‌متر برای هر برگ (دو صفحه) + جلد."""
    return round(pages / 2 * 0.09 + 1.2, 1)


def _layer(cx, cy, w, d, fill, stroke, inner=""):
    """یک لایه‌ی ایزومتریک (لوزی) با محتوای داخلی برش‌خورده."""
    pts = f"{cx},{cy - d} {cx + w},{cy} {cx},{cy + d} {cx - w},{cy}"
    return f'<g><polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width=".5"/>{inner}</g>'


def layers_art() -> str:
    rnd = random.Random(7)
    cx, w, d = 85, 58, 30
    defs, out = [], []
    # لایه‌ی پایین: تصویر ماهواره‌ای (نوارهای رنگی مزرعه)
    clip = lambda i, cy: f'<clipPath id="c{i}"><polygon points="{cx},{cy - d} {cx + w},{cy} {cx},{cy + d} {cx - w},{cy}"/></clipPath>'  # noqa: E731
    cy0 = 168
    defs.append(clip(0, cy0))
    tiles = []
    greens = ["#2f7d4a", "#5a9a3c", "#8bb04a", "#c9b46a", "#a67c3d", "#3d8a6a", "#6fa65a"]
    for i in range(-6, 7):
        for j in range(-4, 5):
            x, y = cx + (i - j) * 9, cy0 + (i + j) * 4.6
            tiles.append(f'<polygon points="{x},{y - 4.6} {x + 9},{y} {x},{y + 4.6} {x - 9},{y}" fill="{rnd.choice(greens)}" opacity=".95"/>')
    river = f'<path d="M{cx - 60},{cy0 + 6} C{cx - 20},{cy0 - 10} {cx + 10},{cy0 + 18} {cx + 60},{cy0 - 4}" stroke="#3aa6c9" stroke-width="2.6" fill="none"/>'
    out.append(_layer(cx, cy0, w, d, "#2f6e4a", "#ffffff55", f'<g clip-path="url(#c0)">{"".join(tiles)}{river}</g>'))
    # لایه‌ی میانی: چندضلعی‌های کاربری
    cy1 = 132
    defs.append(clip(1, cy1))
    polys = []
    cols = ["#f4c98a", "#e8a95b", "#cfe7e3", "#9fd0c8", "#ffffff"]
    for _ in range(16):
        x, y = cx + rnd.uniform(-50, 50), cy1 + rnd.uniform(-24, 24)
        r = rnd.uniform(7, 14)
        pts = " ".join(f"{x + r * math.cos(t) * 1.6:.1f},{y + r * math.sin(t) * .8:.1f}" for t in [k * math.pi / 3 + rnd.uniform(-.3, .3) for k in range(6)])
        polys.append(f'<polygon points="{pts}" fill="{rnd.choice(cols)}" opacity=".55" stroke="#ffffff" stroke-width=".4"/>')
    out.append(_layer(cx, cy1, w, d, "#ffffff22", "#ffffff88", f'<g clip-path="url(#c1)">{"".join(polys)}</g>'))
    # لایه‌ی بالا: شبکه‌ی معابر و نقطه‌ها
    cy2 = 96
    defs.append(clip(2, cy2))
    lines = []
    for k in range(-5, 6):
        lines.append(f'<line x1="{cx - w + k * 10}" y1="{cy2 - 40}" x2="{cx + k * 10 + 30}" y2="{cy2 + 40}" stroke="#ffffff" stroke-width=".5" opacity=".55"/>')
        lines.append(f'<line x1="{cx + w - k * 10}" y1="{cy2 - 40}" x2="{cx - k * 10 - 30}" y2="{cy2 + 40}" stroke="#ffffff" stroke-width=".5" opacity=".55"/>')
    path = f'<path d="M{cx - 40},{cy2 + 4} L{cx - 18},{cy2 - 7} L{cx + 6},{cy2 + 5} L{cx + 34},{cy2 - 9}" stroke="#f4c98a" stroke-width="1.8" fill="none" stroke-linejoin="round"/>'
    pts = "".join(f'<circle cx="{cx + rnd.uniform(-44, 44):.1f}" cy="{cy2 + rnd.uniform(-18, 18):.1f}" r="1.5" fill="#f4c98a"/>' for _ in range(14))
    out.append(_layer(cx, cy2, w, d, "#ffffff14", "#ffffffaa", f'<g clip-path="url(#c2)">{"".join(lines)}{path}{pts}</g>'))
    # پین مکان
    pin = (f'<g transform="translate({cx + 34},{cy2 - 26})"><path d="M0,0 C-7,-10 -7,-20 0,-22 C7,-20 7,-10 0,0Z" fill="#f4c98a"/>'
           f'<circle cx="0" cy="-15" r="2.6" fill="#0a4f50"/></g>')
    # ماهواره و مدار
    orbit = f'<ellipse cx="{cx}" cy="58" rx="74" ry="16" fill="none" stroke="#ffffff" stroke-width=".4" stroke-dasharray="1.6 2.2" opacity=".7"/>'
    sat = (f'<g transform="translate({cx + 52},46) rotate(-18)"><rect x="-3" y="-2.2" width="6" height="4.4" rx=".8" fill="#ffffff"/>'
           f'<rect x="-15" y="-1.6" width="10" height="3.2" fill="#9fd0c8"/><rect x="5" y="-1.6" width="10" height="3.2" fill="#9fd0c8"/></g>'
           f'<path d="M{cx + 50},50 L{cx + 20},{cy2 - 2} L{cx + 48},{cy2 + 6} Z" fill="#f4c98a" opacity=".16"/>')
    # خطوط عمودی اتصال لایه‌ها (مثل کیک لایه‌ها)
    conn = "".join(f'<line x1="{x}" y1="{cy2}" x2="{x}" y2="{cy0}" stroke="#ffffff" stroke-width=".3" stroke-dasharray="1 1.5" opacity=".6"/>' for x in (cx - w, cx + w))
    return (f'<svg viewBox="0 22 170 180" xmlns="http://www.w3.org/2000/svg"><defs>{"".join(defs)}</defs>'
            f'{orbit}{conn}{"".join(out)}{sat}{pin}</svg>')


def contours(seed=3, color="#ffffff", op=.08) -> str:
    rnd = random.Random(seed)
    out = []
    for c in range(3):
        cx, cy = rnd.uniform(0, W), rnd.uniform(0, H)
        for k in range(1, 22):
            r = k * 6.5
            pts = " ".join(f"{cx + r * (1 + .15 * math.sin(3 * t + c)) * math.cos(t) * 1.2:.1f},{cy + r * (1 + .12 * math.cos(4 * t)) * math.sin(t):.1f}"
                           for t in [a * math.pi / 30 for a in range(61)])
            out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width=".3" opacity="{op}"/>')
    return f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice" style="position:absolute;inset:0;width:100%;height:100%">{"".join(out)}</svg>'


CSS = """
@font-face { font-family: Vazirmatn; font-weight: 400; src: url("../../../static/fonts/vazirmatn-arabic-400-normal.woff2"); }
@font-face { font-family: Vazirmatn; font-weight: 700; src: url("../../../static/fonts/vazirmatn-arabic-700-normal.woff2"); }
@font-face { font-family: VazirmatnL; font-weight: 400; src: url("../../../static/fonts/vazirmatn-latin-400-normal.woff2"); }
@font-face { font-family: Kufi; font-weight: 800; src: url("../../../static/fonts/noto-kufi-arabic-arabic-800-normal.woff2"); }
@font-face { font-family: Kufi; font-weight: 700; src: url("../../../static/fonts/noto-kufi-arabic-arabic-700-normal.woff2"); }
@font-face { font-family: KufiL; font-weight: 800; src: url("../../../static/fonts/noto-kufi-arabic-latin-800-normal.woff2"); }
@font-face { font-family: Mono; src: url("../../../static/fonts/jetbrains-mono-latin-500-normal.woff2"); }
* { box-sizing: border-box; }
html, body { margin: 0; direction: rtl; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: VazirmatnL, Vazirmatn, sans-serif; color: #fff; }
.pg { position: relative; overflow: hidden; background: linear-gradient(165deg, #083d3e 0%, #0a4f50 38%, #0f6e6e 100%); }
.front .art { position: absolute; left: 50%; transform: translateX(-50%); width: 112mm; top: 94mm; }
.front .kick { position: absolute; top: 20mm; right: 18mm; left: 18mm; font: 700 9.5pt Kufi, sans-serif; color: #f4c98a; letter-spacing: .3pt; }
.front h1 { position: absolute; top: 30mm; right: 18mm; left: 18mm; margin: 0; font: 800 34pt/1.3 KufiL, Kufi, sans-serif; }
.front h1 span { display:block; color:#f4c98a; }
.front .sub { position: absolute; top: 76mm; right: 18mm; left: 18mm; font-size: 11pt; line-height: 1.8; color: #d8ecea; }
.front .chips { position: absolute; bottom: 27mm; right: 18mm; left: 18mm; display: flex; gap: 2.5mm; flex-wrap: wrap; justify-content: center; }
.front .chips span { border: .6pt solid #ffffff66; border-radius: 10mm; padding: .8mm 3.6mm; font-size: 8.6pt; color: #fff; background: #ffffff10; }
.front .foot { position: absolute; bottom: 14mm; right: 18mm; left: 18mm; display: flex; justify-content: space-between; align-items: baseline; font-size: 9pt; color: #cfe7e3; }
.front .foot b { font: 700 10.5pt Kufi, sans-serif; color: #fff; }
.front .ribbon { position: absolute; top: 0; left: 18mm; width: 11mm; height: 26mm; background: #b8741a;
  clip-path: polygon(0 0, 100% 0, 100% 100%, 50% 82%, 0 100%); }
.back .in { position: absolute; top: 20mm; right: 18mm; left: 18mm; bottom: 46mm; }
.back h2 { font: 800 14pt/1.6 Kufi, sans-serif; margin: 0 0 4mm; color: #fff; }
.back p { font-size: 9.6pt; line-height: 2; text-align: justify; color: #e3f1ef; margin: 0 0 3mm; }
.back h3 { font: 700 9.8pt Kufi, sans-serif; color: #f4c98a; margin: 5mm 0 1.5mm; }
.back ul { margin: 0; padding-right: 4.5mm; font-size: 8.9pt; line-height: 1.95; color: #fff; columns: 2; column-gap: 6mm; }
.back ul li { break-inside: avoid; }
.back ul li::marker { color: #f4c98a; }
.back .aud { display: flex; flex-wrap: wrap; gap: 2mm; }
.back .aud span { background: #ffffff18; border-radius: 1.2mm; padding: .5mm 2.4mm; font-size: 8.4pt; }
.back .code { direction: ltr; text-align: left; font: 7.6pt/1.55 Mono, monospace; color: #cfe7e3; background: #00000030;
  border-right: 1.2mm solid #f4c98a; border-radius: 1.4mm; padding: 2.2mm 3mm; margin-top: 4mm; white-space: pre; }
.back .bar { position: absolute; bottom: 14mm; left: 18mm; width: 44mm; height: 24mm; background: #fff; border-radius: 1mm; color: #1d2a2c;
  display: flex; flex-direction: column; align-items: center; justify-content: center; font-size: 7pt; }
.back .bar .lines { width: 36mm; height: 12mm; background: repeating-linear-gradient(90deg, #1d2a2c 0 .5mm, #fff .5mm 1mm, #1d2a2c 1mm 1.8mm, #fff 1.8mm 2.2mm); margin-bottom: 1mm; opacity: .18; }
.back .pub { position: absolute; bottom: 16mm; right: 18mm; font-size: 8.6pt; color: #cfe7e3; line-height: 1.8; }
.back .pub b { font: 700 10pt Kufi, sans-serif; color: #fff; }
.spine { position: relative; overflow: hidden; background: #083d3e; border-left: .2mm solid #ffffff22; border-right: .2mm solid #ffffff22; }
.spine .t { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%) rotate(90deg); white-space: nowrap;
  display: flex; gap: 8mm; align-items: center; font: 800 10pt Kufi, sans-serif; }
.spine .t i { font-style: normal; font: 400 8pt Vazirmatn, sans-serif; color: #f4c98a; }
"""


def title_lines(t: str) -> str:
    w = t.split()
    if len(w) < 4:
        return html.escape(t)
    return f"{html.escape(' '.join(w[:2]))}<span>{html.escape(' '.join(w[2:]))}</span>"


def front(book) -> str:
    chips = "".join(f"<span>{html.escape(c)}</span>" for c in book.get("cover_chips", []))
    return f'''<div class="pg front" style="width:{W}mm;height:{H}mm">{contours(3)}<div class="ribbon"></div>
<div class="kick">{html.escape(book.get("cover_kicker", ""))}</div>
<h1>{title_lines(book["title"])}</h1><div class="sub">{html.escape(book["subtitle"])}</div>
<div class="art">{layers_art()}</div><div class="chips">{chips}</div>
<div class="foot"><b>{html.escape(book.get("author", ""))}</b><span>{html.escape(book.get("edition", ""))}</span></div></div>'''


def back(book) -> str:
    b = book["back_cover"]
    learn = "".join(f"<li>{html.escape(x)}</li>" for x in b["learn"])
    aud = "".join(f"<span>{html.escape(x)}</span>" for x in b["audience"])
    paras = "".join(f"<p>{html.escape(x)}</p>" for x in b["blurb"])
    return f'''<div class="pg back" style="width:{W}mm;height:{H}mm">{contours(9)}<div class="in">
<h2>{html.escape(b["headline"])}</h2>{paras}<h3>در این کتاب</h3><ul>{learn}</ul>
<h3>برای چه کسانی</h3><div class="aud">{aud}</div><div class="code">{html.escape(b["code"])}</div></div>
<div class="pub"><b>{html.escape(book.get("publisher", ""))}</b><br>{html.escape(fa(book.get("edition", "")))}</div>
<div class="bar"><div class="lines"></div>شابک: {html.escape(fa(book.get("isbn", "۹۷۸-۰۰۰-۰۰۰-۰۰۰-۰")))}</div></div>'''


def cover_html(book, kind: str, pages: int) -> str:
    if kind == "front":
        body, size = front(book), (W, H)
    elif kind == "back":
        body, size = back(book), (W, H)
    else:
        s = spine_mm(pages)
        spine = (f'<div class="spine" style="width:{s}mm;height:{H}mm"><div class="t">{html.escape(book["title"])}'
                 f'<i>{html.escape(book.get("author", ""))}</i></div></div>')
        # چپ به راست روی کاغذ: پشت جلد | عطف | روی جلد (کتاب فارسی از راست باز می‌شود)
        body = f'<div style="display:flex;direction:ltr;padding:{BLEED}mm;background:#083d3e">{back(book)}{spine}{front(book)}</div>'
        size = (2 * W + s + 2 * BLEED, H + 2 * BLEED)
    return (f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><style>{CSS}'
            f'@page {{ size: {size[0]}mm {size[1]}mm; margin: 0; }}</style></head><body>{body}</body></html>')
