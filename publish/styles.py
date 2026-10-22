"""سبک نقشه یک لایه (رنگ‌آمیزی، برچسب، پنجره اطلاعات): پیش‌فرض‌ها و پاک‌سازی ورودی کاربر.

هم طراح نقشه تک‌لایه (publish) و هم نقشه‌های چندلایه (maps) از همین‌جا استفاده می‌کنند.
"""
from __future__ import annotations

import re

STYLE_DEFAULT = {"mode": "single", "color": "#0F5C59", "opacity": 0.75, "size": 6, "outline": "#FFFFFF",
                 "field": "", "classes": 5, "palette": "YlOrRd", "breaks": [], "categories": [], "popup": [],
                 "basemap": "iran", "label": "", "label_color": "#1B2B2F", "label_size": 12}
BASEMAPS = ("iran", "osm", "none")
PALETTES = {
    "YlOrRd": ["#ffffb2", "#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#e31a1c", "#bd0026", "#800026", "#4d0019"],
    "Blues": ["#eff3ff", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#08519c", "#08306b", "#041d43"],
    "Greens": ["#edf8e9", "#c7e9c0", "#a1d99b", "#74c476", "#41ab5d", "#238b45", "#006d2c", "#00441b", "#00290f"],
    "Viridis": ["#440154", "#472d7b", "#3b528b", "#2c728e", "#21918c", "#28ae80", "#5ec962", "#addc30", "#fde725"],
    "RdYlGn": ["#d73027", "#f46d43", "#fdae61", "#fee08b", "#ffffbf", "#d9ef8b", "#a6d96a", "#66bd63", "#1a9850"],
    "Teal": ["#e6f2ef", "#c2e0d8", "#9dcdc1", "#78baa9", "#53a792", "#2e947a", "#0f7e66", "#0f5c59", "#073b3a"],
}
CATEGORY_COLORS = ["#0F5C59", "#E0A526", "#B42318", "#2B6CB0", "#7A4FB5", "#1A7F4B", "#D9480F", "#5C7080",
                   "#C2185B", "#0097A7", "#8D6E63", "#9E9D24"]

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def clean(data, names: set[str]) -> dict:
    """فقط کلیدهای شناخته‌شده با مقدار معتبر؛ ستون‌ها باید در names باشند."""
    if not isinstance(data, dict):
        data = {}
    style = {k: data[k] for k in STYLE_DEFAULT if k in data}
    style["mode"] = style.get("mode") if style.get("mode") in ("single", "graduated", "categorized") else "single"
    style["palette"] = style.get("palette") if style.get("palette") in PALETTES else "YlOrRd"
    style["basemap"] = style.get("basemap") if style.get("basemap") in BASEMAPS else "osm"
    for k, lo, hi in (("opacity", 0.05, 1), ("size", 1, 40), ("classes", 2, 9)):
        try:
            style[k] = max(lo, min(hi, float(style.get(k, STYLE_DEFAULT[k]))))
        except (TypeError, ValueError):
            style[k] = STYLE_DEFAULT[k]
    style["classes"] = int(style["classes"])
    try:
        style["label_size"] = int(max(8, min(24, float(style.get("label_size", 12)))))
    except (TypeError, ValueError):
        style["label_size"] = 12
    for k in ("color", "outline", "label_color"):
        if not HEX_RE.match(str(style.get(k, ""))):
            style[k] = STYLE_DEFAULT[k]
    try:
        style["breaks"] = [float(b) for b in style.get("breaks", [])][:8]
    except (TypeError, ValueError):
        style["breaks"] = []
    cats = style.get("categories", [])
    style["categories"] = [{"value": str(c.get("value", ""))[:200], "color": c["color"]}
                           for c in (cats if isinstance(cats, list) else [])[:12]
                           if isinstance(c, dict) and HEX_RE.match(str(c.get("color", "")))]
    popup = style.get("popup", [])
    style["popup"] = [c for c in (popup if isinstance(popup, list) else []) if isinstance(c, str) and c in names][:12]
    if not isinstance(style.get("field"), str) or style["field"] not in names:
        style["field"], style["mode"] = "", "single"
    if not isinstance(style.get("label"), str) or style["label"] not in names:
        style["label"] = ""
    return style
