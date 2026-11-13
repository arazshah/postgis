"""پیش‌نمایش «داده‌ی نمونه» برای استودیوی دیداری (docs/adr/0010): بدون پایگاه داده و بدون ورود دومرحله‌ای.

از نوع و نام ستون‌های جدول‌های نقشه ردیف واقع‌نما (نام فارسی، مختصات تهران) می‌سازد و بلوک‌های **ساخت‌یافته** را در پایتون ارزیابی می‌کند؛
خروجی همان مدل نمایش `pagekit.render_block` است، پس قالب `kernel/_page_body.html` بی‌تغییر آن را نشان می‌دهد. این نمای تقریبی است:
بلوک «SQL پیشرفته» و «خروجی کد» بدون پایگاه واقعی نمونه ندارند و جایگزین توضیحی می‌گیرند. چیزی نوشته یا خوانده نمی‌شود.
"""
from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

from . import pagekit, wizard

N_ROWS = 40
NAMES = ("علی رضایی", "مریم احمدی", "حسین کریمی", "زهرا موسوی", "رضا نوری", "سارا حسینی", "محمد قاسمی", "نگار صادقی")
PLACES = ("تهران", "کرج", "شیراز", "تبریز", "اصفهان", "مشهد", "اهواز", "رشت")
DEVICES = ("دستگاه ۱", "دستگاه ۲", "دستگاه ۳", "دستگاه ۴", "دستگاه ۵")
STATUS = ("فعال", "در انتظار", "تمام‌شده")
TEHRAN = (35.60, 35.80, 51.25, 51.55)  # عرض کم/زیاد، طول کم/زیاد
PLACEHOLDER = {"sql": "SQL پیشرفته روی پایگاه واقعی اجرا می‌شود؛ برای دیدنش «داده‌ی واقعی» را بزنید.",
               "handler": "خروجی کد فقط در اجرای آزمایشی یا روی پایگاه واقعی دیده می‌شود."}


def _text(rng: random.Random, name: str, i: int) -> str:
    n = name.lower()
    if any(k in n for k in ("device", "sensor", "unit", "dev")):
        return DEVICES[i % len(DEVICES)]
    if any(k in n for k in ("name", "title", "owner", "user", "person")):
        return NAMES[i % len(NAMES)]
    if any(k in n for k in ("city", "place", "region", "area", "village")):
        return PLACES[i % len(PLACES)]
    if any(k in n for k in ("status", "state", "kind", "type")):
        return STATUS[i % len(STATUS)]
    return f"نمونه {i % 9 + 1}"


def _num(rng: random.Random, col: dict, integer: bool):
    lo = col["min"] if isinstance(col.get("min"), (int, float)) and not isinstance(col.get("min"), bool) else 0
    hi = col["max"] if isinstance(col.get("max"), (int, float)) and not isinstance(col.get("max"), bool) else 100
    if col["name"].lower() in ("lat", "latitude"):
        lo, hi = max(lo, TEHRAN[0]), min(hi, TEHRAN[1])
    elif col["name"].lower() in ("lon", "lng", "longitude"):
        lo, hi = max(lo, TEHRAN[2]), min(hi, TEHRAN[3])
    v = rng.uniform(lo, hi)
    return int(round(v)) if integer else round(v, 4 if "lat" in col["name"].lower() or "lon" in col["name"].lower() else 2)


def rows(table: dict, n: int = N_ROWS, seed: int = 7) -> list[dict]:
    """n ردیف نمونه‌ی `{ستون: مقدار}` برای یک جدول نقشه. قطعی (یک seed = یک خروجی)."""
    rng = random.Random(f"{seed}:{table['name']}")
    now = datetime.now(UTC).replace(microsecond=0)
    out = []
    for i in range(n):
        r: dict = {"id": i + 1}
        for c in table.get("columns") or []:
            t, nm = c["type"], c["name"]
            if t == "text":
                r[nm] = _text(rng, nm, i)
            elif t in ("integer", "bigint"):
                r[nm] = _num(rng, c, True)
            elif t == "double":
                r[nm] = _num(rng, c, False)
            elif t == "boolean":
                r[nm] = rng.random() < 0.5
            elif t == "timestamptz":
                r[nm] = now - timedelta(minutes=i * 3 + rng.randint(0, 2))
            elif t == "date":
                r[nm] = (now - timedelta(days=i)).date()
            elif t == "point":
                r[nm] = (round(rng.uniform(TEHRAN[2], TEHRAN[3]), 4), round(rng.uniform(TEHRAN[0], TEHRAN[1]), 4))
            elif t == "jsonb":
                r[nm] = {}
            else:
                r[nm] = None
        out.append(r)
    return out


def _since(data: list[dict], b: dict) -> list[dict]:
    col, mins = b.get("since_col"), b.get("since_minutes")
    if not col or not mins:
        return data
    try:
        limit = datetime.now(UTC) - timedelta(minutes=int(mins))
    except (TypeError, ValueError):
        return data
    out = []
    for r in data:
        v = r.get(col)
        if isinstance(v, datetime):
            keep = v > limit
        elif isinstance(v, date):
            keep = datetime(v.year, v.month, v.day, tzinfo=UTC) > limit
        else:
            keep = True
        if keep:
            out.append(r)
    return out


def _agg(agg: str, vals: list):
    nums = [float(v) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if agg == "count":
        return len(vals)
    if not nums:
        return None
    return {"sum": sum(nums), "avg": sum(nums) / len(nums), "min": min(nums), "max": max(nums)}[agg]


def _width(b: dict, default: str = "full") -> str:
    return b.get("width") if b.get("width") in pagekit.WIDTHS else default


def _base(b: dict, default_width: str = "full") -> dict:
    return {"kind": b["kind"], "title": b.get("title", ""), "width": _width(b, default_width), "hint": "", "error": "", "id": b.get("id", "")}


def render_block(spec: dict, b: dict, data: dict[str, list[dict]]) -> dict:
    """بلوک نقشه ← مدل نمایش (همان کلیدهای pagekit.render_block). ایراد بلوک = پیام خطا در همان بلوک، نه استثنا."""
    kind = b.get("kind")
    if kind == "text":
        out = _base(b)
        out["paras"] = [p.strip() for p in str(b.get("text", "")).split("\n\n") if p.strip()]
        return out
    if kind in wizard.ACTIONS or kind in wizard.FILE_ACTIONS:
        return {**_base(b), "kind": "action", "action": kind, "error": ""}
    if kind in ("sql", "handler"):
        shown = b.get("display")
        out = _base({**b, "kind": shown if shown in ("kpi", "table", "bars", "map") else "table"})
        out["error"] = PLACEHOLDER[kind]
        out["placeholder"] = True
        return out
    out = _base(b, "third" if kind == "kpi" else "full")
    try:
        wizard.check_block(spec, b)
        t = wizard.table_map(spec)[b["table"]]
    except (wizard.WizardError, KeyError) as exc:
        out["error"] = str(exc) if isinstance(exc, wizard.WizardError) else "جدول بلوک را انتخاب کنید."
        return out
    d = _since(data.get(t["name"]) or [], b)
    if kind == "kpi":
        if b.get("agg", "count") == "count" and b.get("distinct"):
            v = len({r.get(b["distinct"]) for r in d})
        else:
            col = b.get("column")
            v = _agg(b.get("agg", "count"), [r.get(col) for r in d] if col else d)
        out.update(value=pagekit._fmt(v) if v is not None else "—", unit=str(b.get("unit", "")))
    elif kind == "table":
        cols = b.get("columns") or [c["name"] for c in t["columns"]][:6]
        order = b.get("order_by") or "id"
        d = sorted(d, key=lambda r: (r.get(order) is None, r.get(order)), reverse=bool(b.get("desc", True)))[: int(b.get("limit") or 20)]
        out.update(headers=list(cols), rows=[[pagekit._fmt(r.get(c)) for c in cols] for r in d], truncated=False)
    elif kind == "bars":
        groups: dict[str, list] = {}
        for r in d:
            groups.setdefault(str(r.get(b["label"])), []).append(r)
        col = b.get("column")
        vals = {k: _agg(b.get("agg", "count"), [r.get(col) for r in rs] if col else rs) or 0 for k, rs in groups.items()}
        top = max([float(v) for v in vals.values()] + [1.0])
        out["bars"] = [{"label": k, "value": pagekit._fmt(v), "pct": round(float(v) * 100 / top)}
                       for k, v in sorted(vals.items(), key=lambda kv: -kv[1])[:20]]
    elif kind == "map":
        if b.get("latest_by"):
            seen, latest = set(), []
            for r in sorted(d, key=lambda r: r.get(b["time_col"]) or datetime.min.replace(tzinfo=UTC), reverse=True):
                if r.get(b["latest_by"]) not in seen:
                    seen.add(r.get(b["latest_by"]))
                    latest.append(r)
            d = latest
        feats = []
        for r in d[:2000]:
            xy = r.get(b["point"]) if b.get("point") else (r.get(b.get("lon")), r.get(b.get("lat")))
            if not xy or None in xy:
                continue
            props = {c: pagekit._fmt(r.get(c)) for c in (b.get("props") or []) if c}
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [xy[0], xy[1]]}, "properties": props})
        out["geojson"] = {"type": "FeatureCollection", "features": feats}
        out["count"] = len(feats)
    return out


def preview(spec: dict, page_key: str, seed: int = 7) -> dict:
    """نمای نمونه‌ی یک صفحه‌ی نقشه: {page، blocks، actions، sample: True}. ValueError اگر صفحه نیست."""
    page = next((p for p in spec.get("pages") or [] if p.get("key") == page_key), None)
    if page is None:
        raise ValueError("صفحه‌ای با این کلید نیست.")
    data = {t["name"]: rows(t, seed=seed) for t in spec.get("tables") or [] if t.get("name") and t.get("columns")}
    blocks = [render_block(spec, b, data) for b in page.get("blocks") or []]
    return {"page": page, "blocks": [b for b in blocks if b["kind"] != "action"], "actions": [b for b in blocks if b["kind"] == "action"],
            "all_blocks": blocks, "param_errors": [], "sample": True, "has_map": any(b["kind"] == "map" for b in blocks)}
