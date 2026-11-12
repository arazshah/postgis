"""چیدمان قابل‌ویرایش گزارش PDF (ADR-0009 مرحله‌ی ۴): کاربر عنصرها را اضافه، حذف، جابه‌جا و تنظیم می‌کند.

چیدمان یک JSON کوچک و **کاملاً اعتبارسنجی‌شده** است (نوع عنصر، اندازه و رنگ فقط از فهرست سفید؛ متن‌ها در خروجی escape می‌شوند).
هیچ HTML/CSS/SVG آزاد از کاربر پذیرفته نمی‌شود؛ لوگو با Pillow بازکدگذاری می‌شود (بدون متادیتا/چندریختی).
"""
from __future__ import annotations

import io
import re
import secrets

MAX_ELEMENTS, MAX_TEXT, MAX_LOGO_BYTES, LOGO_MAX_PX = 40, 2000, 1_000_000, 600
SIZES = {"sm": 9, "md": 11, "lg": 15, "xl": 20}
COLORS = {"primary": "#0F5C59", "accent": "#B7791F", "ink": "#1F2933", "muted": "#7A7566"}
ALIGNS = ("right", "center", "left")
TYPES = ("logo", "title", "text", "meta", "block", "divider", "spacer", "pagebreak")
TYPE_LABELS = {"logo": "لوگو", "title": "عنوان", "text": "متن", "meta": "اطلاعات گزارش", "block": "بخش داده (جدول، نقشه…)",
               "divider": "خط جداکننده", "spacer": "فاصله", "pagebreak": "صفحه‌ی جدید"}
PLACEHOLDERS = ("date", "db", "site", "page", "filters")
_PH = re.compile(r"\{(date|db|site|page|filters)\}")
ID_RE = re.compile(r"^[a-z0-9]{2,12}$")


def new_id() -> str:
    return secrets.token_hex(3)


def fill(text: str, ctx: dict) -> str:
    """جای‌نگهدارهای ثابت ({date}، {db}، {site}، {page}، {filters}) را پر می‌کند؛ هر چیز دیگر همان‌طور می‌ماند."""
    return _PH.sub(lambda m: str(ctx.get(m.group(1), "")), text)


def default_layout(report, n_blocks: int) -> dict:
    """چیدمان پیش‌فرض از مشخصات `[[reports]]`: لوگو، عنوان، اطلاعات، خط، بخش‌ها."""
    idx = list(report.blocks) or list(range(1, n_blocks + 1))
    els = [{"id": new_id(), "type": "logo", "align": "right", "height_mm": 16},
           {"id": new_id(), "type": "title", "text": report.title, "subtitle": report.subtitle, "align": "right", "size": "xl", "color": "primary"},
           {"id": new_id(), "type": "meta", "show_site": True, "show_db": True, "show_date": True, "show_filters": True, "align": "right"},
           {"id": new_id(), "type": "divider", "color": "primary"}]
    els += [{"id": new_id(), "type": "block", "index": i, "hide_title": False, "title": "", "height_mm": 90} for i in idx]
    return {"version": 1, "page": {"orientation": "landscape" if report.landscape else "portrait", "margin_mm": 14, "font_scale": 1.0,
                                   "footer": "", "page_numbers": True}, "elements": els}


def _s(d: dict, k: str, limit: int, default: str = "") -> str:
    v = d.get(k, default)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ValueError(f"«{k}» باید متن باشد.")
    v = v.replace("\x00", "").strip()
    if len(v) > limit:
        raise ValueError(f"«{k}» حداکثر {limit} نویسه است.")
    return v


def _choice(d: dict, k: str, allowed, default):
    v = d.get(k, default)
    if v not in allowed:
        raise ValueError(f"مقدار «{k}» نامعتبر است.")
    return v


def _num(d: dict, k: str, lo: float, hi: float, default: float, integer: bool = True):
    v = d.get(k, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        raise ValueError(f"«{k}» باید عدد باشد.")
    if not lo <= v <= hi:
        raise ValueError(f"«{k}» باید بین {lo} و {hi} باشد.")
    return int(v) if integer else round(float(v), 2)


def _bool(d: dict, k: str, default: bool) -> bool:
    v = d.get(k, default)
    if not isinstance(v, bool):
        raise ValueError(f"«{k}» باید بله/خیر باشد.")
    return v


def validate(raw, n_blocks: int) -> dict:
    """JSON خام کاربر ← چیدمان هنجارشده (فقط کلیدهای شناخته‌شده)؛ ValueError با پیام فارسی."""
    if not isinstance(raw, dict):
        raise ValueError("چیدمان نامعتبر است.")
    pg = raw.get("page") or {}
    if not isinstance(pg, dict):
        raise ValueError("تنظیم صفحه نامعتبر است.")
    page = {"orientation": _choice(pg, "orientation", ("portrait", "landscape"), "portrait"),
            "margin_mm": _num(pg, "margin_mm", 8, 30, 14), "font_scale": _num(pg, "font_scale", 0.8, 1.4, 1.0, integer=False),
            "footer": _s(pg, "footer", 200), "page_numbers": _bool(pg, "page_numbers", True)}
    els_raw = raw.get("elements")
    if not isinstance(els_raw, list) or len(els_raw) > MAX_ELEMENTS:
        raise ValueError(f"حداکثر {MAX_ELEMENTS} عنصر.")
    els, seen = [], set()
    for e in els_raw:
        if not isinstance(e, dict) or e.get("type") not in TYPES:
            raise ValueError("نوع عنصر نامعتبر است.")
        t = e["type"]
        eid = e.get("id") if isinstance(e.get("id"), str) and ID_RE.fullmatch(e.get("id", "")) else new_id()
        while eid in seen:
            eid = new_id()
        seen.add(eid)
        out = {"id": eid, "type": t}
        if t == "logo":
            out.update(align=_choice(e, "align", ALIGNS, "right"), height_mm=_num(e, "height_mm", 6, 40, 16))
        elif t == "title":
            out.update(text=_s(e, "text", 200), subtitle=_s(e, "subtitle", 240), align=_choice(e, "align", ALIGNS, "right"),
                       size=_choice(e, "size", tuple(SIZES), "xl"), color=_choice(e, "color", tuple(COLORS), "primary"))
        elif t == "text":
            out.update(text=_s(e, "text", MAX_TEXT), align=_choice(e, "align", ALIGNS, "right"), size=_choice(e, "size", tuple(SIZES), "md"),
                       color=_choice(e, "color", tuple(COLORS), "ink"), bold=_bool(e, "bold", False))
        elif t == "meta":
            out.update(align=_choice(e, "align", ALIGNS, "right"), **{k: _bool(e, k, True) for k in ("show_site", "show_db", "show_date", "show_filters")})
        elif t == "block":
            out.update(index=_num(e, "index", 1, max(n_blocks, 1), 1), hide_title=_bool(e, "hide_title", False), title=_s(e, "title", 80),
                       height_mm=_num(e, "height_mm", 40, 200, 90))
        elif t == "divider":
            out.update(color=_choice(e, "color", tuple(COLORS), "primary"))
        elif t == "spacer":
            out.update(height_mm=_num(e, "height_mm", 2, 60, 8))
        els.append(out)
    return {"version": 1, "page": page, "elements": els}


def referenced_blocks(layout: dict) -> list[int]:
    return sorted({e["index"] for e in layout["elements"] if e["type"] == "block"})


def process_logo(data: bytes) -> tuple[bytes, str]:
    """تصویر بارگذاری‌شده ← (PNG یا JPEG بازکدگذاری‌شده، mime). فقط PNG/JPEG؛ SVG و بقیه رد می‌شود."""
    if not data or len(data) > MAX_LOGO_BYTES:
        raise ValueError("لوگو حداکثر ۱ مگابایت و غیرخالی باشد.")
    from PIL import Image, UnidentifiedImageError

    try:
        im = Image.open(io.BytesIO(data))
        fmt = im.format
        im.verify()
        im = Image.open(io.BytesIO(data))
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise ValueError("فایل تصویر معتبر نیست (فقط PNG یا JPEG).") from None
    if fmt not in ("PNG", "JPEG"):
        raise ValueError("فقط PNG یا JPEG پذیرفته می‌شود.")
    if im.width * im.height > 25_000_000:
        raise ValueError("ابعاد تصویر بیش از حد بزرگ است.")
    im.thumbnail((LOGO_MAX_PX, LOGO_MAX_PX))
    out = io.BytesIO()
    if fmt == "PNG" or "A" in im.getbands():
        im.convert("RGBA").save(out, "PNG", optimize=True)
        return out.getvalue(), "image/png"
    im.convert("RGB").save(out, "JPEG", quality=88)
    return out.getvalue(), "image/jpeg"
