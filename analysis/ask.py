"""
پرسش فارسی از داده با s3geo و کلید مدل زبانی خود کاربر.

به مدل زبانی فقط «توصیف» لایه‌ها می‌رود (نام، ستون‌ها، نوع هندسه، تعداد، محدوده)؛ خود عوارض روی همین سرور
پردازش می‌شوند. نتیجه به‌صورت جدول جدید در پایگاه داده کاربر ذخیره می‌شود.
"""
from __future__ import annotations

import json
import re
import tempfile
from dataclasses import asdict, dataclass, replace
from dataclasses import field as dc_field
from datetime import timedelta
from pathlib import Path

from django.utils import timezone
from psycopg import sql

from databases.explorer import Explorer
from databases.gdal import TABLE_RE
from jobs.models import Job

from .models import LlmConfig, Question

LAYER_LIMIT = 50000
MAX_LAYERS = 4
MAX_AUTO_LAYERS = 8
MAX_ATTEMPTS = 3
TABLE_ROW_LIMIT = 100000
DAILY_LIMIT = 40
NAME_RE = re.compile(r"(?:به|با)\s+نام\s+[«\"'`]?([A-Za-z_][A-Za-z0-9_]{2,62})")


class AskError(Exception):
    pass


def _auto_output(text: str) -> str:
    """نام جدول از متن پرسش («… به نام rent_cases») یا نام خودکار بر اساس زمان."""
    m = NAME_RE.search(text)
    if m and TABLE_RE.match(m.group(1).lower()):
        return m.group(1).lower()
    return "ask_" + timezone.now().strftime("%m%d_%H%M%S")


def _auto_layers(text: str, spatial: dict) -> list[str]:
    """لایه‌هایی که کاربر انتخاب نکرده: همه (تا سقف)، یا آن‌هایی که نامشان در پرسش آمده."""
    named = [k for k, t in spatial.items() if len(t.name) > 2 and t.name.lower() in text.lower()]
    if named:
        return named[:MAX_AUTO_LAYERS]
    if len(spatial) <= MAX_AUTO_LAYERS:
        return list(spatial)
    raise AskError(f"بیش از {MAX_AUTO_LAYERS} لایه مکانی دارید؛ لایه‌های مورد نظر را انتخاب کنید.")


def request(db, user, text: str, layer_keys: list[str], output: str, share_values: bool = True) -> Question:
    text = (text or "").strip()
    if len(text) < 8:
        raise AskError("پرسش را کامل‌تر بنویسید.")
    if not LlmConfig.objects.filter(user=user).exists():
        raise AskError("اول کلید مدل زبانی خود را وارد کنید.")
    output = (output or "").strip().lower() or _auto_output(text)
    if not TABLE_RE.match(output):
        raise AskError("نام جدول نتیجه: حروف کوچک لاتین، رقم و _ (مثلاً schools_far_from_metro).")
    tables = {f"{t.schema}.{t.name}": t for t in Explorer(db).tables()}
    spatial = {k: t for k, t in tables.items() if t.geometry}
    notes = []
    given = [k for k in dict.fromkeys(layer_keys or []) if k]
    layer_keys = [k for k in given if k in spatial]
    if given and not layer_keys:
        raise AskError("لایهٔ انتخاب‌شده مکانی نیست یا وجود ندارد.")
    if not layer_keys:
        if not spatial:
            raise AskError("لایه مکانی ندارید؛ اول داده‌ای وارد کنید.")
        layer_keys = _auto_layers(text, spatial)
        notes.append("لایه‌ها خودکار انتخاب شدند: " + "، ".join(k.removeprefix("public.") for k in layer_keys))
    elif len(layer_keys) > MAX_LAYERS:
        raise AskError(f"حداکثر {MAX_LAYERS} لایه.")
    if f"public.{output}" in layer_keys:
        raise AskError("نام جدول نتیجه با یکی از لایه‌های ورودی یکی است.")
    qs = Question.objects.filter(database=db)
    if qs.filter(job__status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).exists():
        raise AskError("یک پرسش در حال پردازش است؛ صبر کنید تمام شود.")
    if Question.objects.filter(user=user, created_at__gte=timezone.now() - timedelta(days=1)).count() >= DAILY_LIMIT:
        raise AskError(f"حداکثر {DAILY_LIMIT} پرسش در روز.")
    job = Job.objects.create(kind=Job.Kind.ASK, database=db, user=user, status=Job.Status.QUEUED)
    return Question.objects.create(database=db, user=user, text=text[:2000], layers=layer_keys, output_table=output,
                                   share_values=share_values, notes=notes, job=job)


def _client(cfg: LlmConfig):
    from s3geo import OpenAICompatibleLLMClient

    return OpenAICompatibleLLMClient(api_key=cfg.get_key(), base_url=cfg.base_url, model=cfg.model, timeout=90)


def _features(out) -> list[dict]:
    if hasattr(out, "map_layers") and out.map_layers:
        return list(out.map_layers[0].get("features", []))
    if hasattr(out, "features"):
        return list(out.features or [])
    if isinstance(out, dict) and "features" in out:
        return list(out["features"])
    return []


def _clean(props: dict) -> dict:
    res = {}
    for k, v in (props or {}).items():
        if str(k).startswith("_"):
            continue
        res[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
    return res


def _max_abs_x(features) -> float:
    best = 0.0

    def walk(c):
        nonlocal best
        if isinstance(c, (int, float)):
            return
        if c and isinstance(c[0], (int, float)):
            best = max(best, abs(float(c[0])))
        else:
            for x in c:
                walk(x)

    for f in features:
        g = f.get("geometry") or {}
        walk(g.get("coordinates") or [])
    return best


# ---------------------------------------------------------------------- راهنمای مدل زبانی
HINTS_BASE = (
    "پاسخ و نام ستون‌های جدید می‌تواند فارسی یا لاتین باشد. "
    "اگر کاربر خروجی «لایه»، «نقشه» یا «عارضه» خواسته، آخرین عملیات باید لایه برداری بدهد و نه summarize_vector یا "
    "attribute_statistics. "
)
HINT_LONGEST = (
    "برای «بلندترین/طولانی‌ترین/بزرگ‌ترین/بیشترین» مقدار یک عارضه: {merge}به CRS متری ببر (crs_transform) و "
    "area_perimeter بزن تا ستون _length (متر) ساخته شود، سپس top_n با score_field=_length و descending=true و limit=1 "
    "بگیر. طول/مساحت را بعد از تبدیل به CRS متری حساب کن، نه روی درجه. "
)
HINT_MERGE = "اگر عارضه‌ها تکه‌تکه‌اند (مثل رودها) ابتدا با dissolve بر اساس ستون نام ادغام کن، سپس "
HINT_FIELD = (
    "اگر کاربر نام مشخصی برای ستون خواست (مثلاً طول به متر)، با calculate_field با عبارت geom_length یا geom_area "
    "ستونی با همان نام بساز. "
)
HINT_DISTANCE = (
    "برای «در X متری»، «نزدیک‌تر از X متر» یا «فاصلهٔ کمتر از X»: هر دو لایه را با crs_transform به CRS متری ببر، سپس "
    "filter_by_distance با max_distance_m=X و drop_unmatched=true بزن؛ بعد از آن دوباره روی _nearest_distance فیلتر نکن. "
)
HINT_ON_LINE = (
    "برای عارضه‌هایی «در/کنار/روی» یک خیابان، رود یا هر لایهٔ خطی، spatial_join با intersects نزن چون نقطه دقیقاً روی خط "
    "نمی‌افتد و نتیجه خالی می‌شود؛ filter_by_distance با فاصلهٔ کم (حدود ۳۰ متر) بزن. اگر نوع خاصی خواسته شده "
    "(مثل خیابان اصلی)، اول همان لایه را با filter_attribute روی ستون نوع (مثل highway، type یا class) جدا کن. "
)
HINT_VALUES = "در شرط where برای ستون‌های متنی فقط یکی از مقادیر واقعی فهرست‌شده را با همان املا به کار ببر. "


def _hints(catalog=None) -> str:
    """راهنمای مدل؛ هر توصیه فقط وقتی داده می‌شود که عملیاتش در نسخهٔ نصب‌شدهٔ s3geo هست.

    سرور ممکن است s3geo قدیمی‌تر از نسخه‌ای داشته باشد که عملیات تازه را دارد؛ توصیهٔ عملیات ناموجود باعث
    «Unsupported operation» می‌شود (نمونه: dissolve در نسخه‌های پیش از ۰٫۶٫۰).
    """
    if catalog is None:
        try:
            from orchestrator.planning.op_catalog import OP_CATALOG as catalog
        except Exception:  # noqa: BLE001  مسیر در این نسخه نیست
            return HINTS_BASE.strip()
    ops = set(catalog)
    text = HINTS_BASE
    if {"crs_transform", "area_perimeter", "top_n"} <= ops:
        text += HINT_LONGEST.format(merge=HINT_MERGE if "dissolve" in ops else "")
    if "calculate_field" in ops:
        text += HINT_FIELD
    if "filter_by_distance" in ops:
        text += HINT_DISTANCE + HINT_ON_LINE
    return text.strip()


MAX_VALUES = 20
MAX_VALUE_CHARS = 40
MAX_VALUE_HINT = 3000


def _value_hints(layers: dict) -> str:
    """مقادیر واقعی ستون‌های دسته‌ای (مثل «اجاره»، «فروش») برای مدل زبانی.

    s3geo فقط نام و نوع ستون‌ها را به مدل می‌دهد؛ مدل مقدار شرط را حدس می‌زند (مثلاً rent به‌جای «اجاره») و فیلتر
    خالی برمی‌گردد. فقط ستون‌هایی فرستاده می‌شوند که چند مقدار تکراری دارند (دسته)، نه نام یا شناسهٔ هر عارضه.
    """
    lines = []
    for name, fc in layers.items():
        values: dict[str, dict] = {}
        filled: dict[str, int] = {}
        for f in (fc or {}).get("features") or []:
            for k, v in ((f or {}).get("properties") or {}).items():
                if not isinstance(v, str) or not v.strip() or str(k).startswith("_"):
                    continue
                filled[k] = filled.get(k, 0) + 1
                seen = values.setdefault(k, {})
                if len(seen) <= MAX_VALUES:
                    seen[v.strip()] = seen.get(v.strip(), 0) + 1
        for k, seen in values.items():
            if not seen or len(seen) > MAX_VALUES or (len(seen) == filled[k] and filled[k] > 3):
                continue
            if any(len(v) > MAX_VALUE_CHARS for v in seen):
                continue
            ordered = sorted(seen, key=lambda v: -seen[v])
            lines.append(f"{name}.{k}: " + "، ".join(f"«{v}»" for v in ordered))
    if not lines:
        return ""
    text = "مقادیر واقعی ستون‌های دسته‌ای لایه‌ها: " + " | ".join(lines)
    return (text[:MAX_VALUE_HINT] + " " + HINT_VALUES).strip()


# ---------------------------------------------------------------------- اصلاح برنامهٔ مدل پیش از اجرا
NEAREST_OPS = {"spatial_nearest", "nearest_neighbor", "filter_by_distance"}


def _patch_spec(spec):
    """با max_distance، عارضه‌های بی‌همسایه فاصلهٔ خالی (None) می‌گیرند و filter_attribute بعدی روی آن می‌شکند
    («'<=' not supported between NoneType and int»)؛ آن‌ها را همان‌جا کنار می‌گذارد که معنای «در X متری» هم همین است."""
    ops = []
    for op in spec.operations:
        p = dict(op.params or {})
        if (op.op in NEAREST_OPS and "drop_unmatched" not in p
                and (p.get("max_distance") is not None or p.get("max_distance_m") is not None)):
            p["drop_unmatched"] = True
            op = replace(op, params=p)
        ops.append(op)
    return replace(spec, operations=ops)


# ---------------------------------------------------------------------- برداشت نتیجه
def _is_vector(out) -> bool:
    return bool(hasattr(out, "map_layers") and out.map_layers) or hasattr(out, "features") or (
        isinstance(out, dict) and "features" in out)


def _spatial_output(result, spec):
    """آخرین خروجی مرحله‌ها که عارضهٔ دارای هندسه دارد؛ از آخر به اول (مرحلهٔ خلاصه‌ساز آخر نباید نتیجه را از بین ببرد).

    اگر آخرین مرحلهٔ لایه‌ساز هیچ عارضه‌ای نداد، نتیجه خالی است: نباید به مرحلهٔ میانی (مثلاً همهٔ خانه‌ها پس از
    تبدیل مختصات) برگشت و آن را به اسم نتیجه ذخیره کرد."""
    for op in reversed(spec.operations):
        out = result.outputs.get(op.output)
        all_feats = _features(out)
        if _is_vector(out) and not all_feats:
            return op.output, []
        feats = [f for f in all_feats if isinstance(f, dict) and f.get("geometry")]
        if feats:
            return op.output, feats
    return None, []


_SKIP_KEYS = {"type", "status", "created_at", "source_info", "metadata", "trace", "map_layers", "layers", "features",
              "geometry", "bbox", "schema_version", "request_id"}
MAX_ANSWER_CHARS = 1500


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _plain(out, depth: int = 0) -> list[str]:
    """خروجی غیرمکانی را به چند خط خوانا برای کاربر تبدیل می‌کند (نه نمایش خام دیکشنری)."""
    if out is None:
        return []
    if hasattr(out, "model_dump"):
        out = out.model_dump()
    elif hasattr(out, "__dict__") and not isinstance(out, (dict, list, str)):
        out = {k: v for k, v in vars(out).items() if not k.startswith("_")}
    if isinstance(out, str):
        return [out.strip()] if out.strip() else []
    if isinstance(out, (int, float, bool)):
        return [_fmt(out)]
    if isinstance(out, dict):
        if out.get("type") == "vector_summary":
            lines = [f"تعداد عارضه: {out.get('feature_count', 0):,}"]
            gc = out.get("geometry_counts") or {}
            if gc:
                lines.append("نوع هندسه: " + "، ".join(f"{k} ({v})" for k, v in gc.items()))
            keys = out.get("property_keys") or []
            if keys:
                lines.append("ستون‌ها: " + "، ".join(map(str, keys[:20])))
            return lines
        lines = []
        for k, v in out.items():
            if k in _SKIP_KEYS or v in (None, "", [], {}):
                continue
            if isinstance(v, dict) and depth < 2:
                inner = _plain(v, depth + 1)
                if inner:
                    lines.append(f"{k}:")
                    lines.extend("  " + x for x in inner)
            elif isinstance(v, list) and v and isinstance(v[0], dict) and depth < 2:
                lines.append(f"{k}:")
                for row in v[:10]:
                    lines.append("  " + "، ".join(f"{a}: {_fmt(b)}" for a, b in row.items() if a not in _SKIP_KEYS))
            else:
                lines.append(f"{k}: {_fmt(v)}")
        return lines
    if isinstance(out, (list, tuple)):
        lines = []
        for row in out[:10]:
            lines.extend(_plain(row, depth + 1) if isinstance(row, (dict, list)) else [_fmt(row)])
        return lines
    return [_fmt(out)]


def _answer_text(result, spec) -> str:
    """پاسخ متنی تحلیل: خروجی آخرین مرحله‌ای که چیز قابل نمایشی دارد."""
    for op in reversed(spec.operations):
        lines = _plain(result.outputs.get(op.output))
        if lines:
            return "\n".join(lines)[:MAX_ANSWER_CHARS]
    return ""


# ---------------------------------------------------------------------- گزارش مرحله‌به‌مرحله
def _fa(n) -> str:
    return f"{n:,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))


def _steps(result, spec, layers: dict) -> list[dict]:
    """زنجیرهٔ «لایهٔ ورودی ← مرحله‌ها» با تعداد عارضهٔ هر کدام، تا کاربر ببیند نتیجه کجا خالی شد."""
    used = {ref for op in spec.operations for ref in (op.inputs or {}).values()}
    steps = [{"op": "input", "name": name, "count": len((fc or {}).get("features") or []), "status": "done"}
             for name, fc in layers.items() if name in used]
    outputs = getattr(result, "outputs", None) or {}
    failed = not getattr(result, "success", True)
    reached_failure = False
    for op in spec.operations:
        if op.output in outputs:
            out = outputs[op.output]
            steps.append({"op": op.op, "name": op.output, "count": len(_features(out)) if _is_vector(out) else None,
                          "status": "done"})
        else:
            status = "failed" if failed and not reached_failure else "skipped"
            reached_failure = reached_failure or status == "failed"
            steps.append({"op": op.op, "name": op.output, "count": None, "status": status})
    return steps


def _conditions(where) -> list[tuple]:
    """(ستون، عملگر، مقدار) از شرط where در هر شکلی: {field, op, value}، کوتاه‌نوشت {ستون: مقدار} یا
    {ستون: {عملگر: مقدار}}، و ترکیب با and/or/not."""
    if isinstance(where, dict):
        if "field" in where:
            return [(str(where.get("field")), str(where.get("op") or where.get("operator") or "eq"), where.get("value"))]
        out = []
        for k, v in where.items():
            if k in ("and", "or", "not", "all", "any"):
                out.extend(_conditions(v))
            elif isinstance(v, dict) and v:
                oper, val = next(iter(v.items()))
                out.append((str(k), str(oper), val))
            else:
                out.append((str(k), "eq", v))
        return out
    if isinstance(where, (list, tuple)):
        return [c for v in where for c in _conditions(v)]
    return []


def _ref_features(ref, result, layers):
    outputs = getattr(result, "outputs", None) or {}
    if ref in outputs:
        return _features(outputs[ref])
    return list(((layers.get(ref) or {}).get("features")) or [])


def _geom_kind(feats) -> str:
    for f in feats:
        t = ((f or {}).get("geometry") or {}).get("type") or ""
        if t:
            return t.removeprefix("Multi")
    return ""


SPATIAL_FILTER_OPS = {"spatial_join", "filter_points_in_polygon", "filter_by_distance", "spatial_nearest",
                      "nearest_neighbor", "spatial_predicate", "intersect", "clip", "overlay"}


def _why_empty(result, spec, layers) -> list[str]:
    """اولین مرحله‌ای که ورودی داشت اما خروجی‌اش خالی شد، و دلیل قابل فهم برای کاربر."""
    outputs = getattr(result, "outputs", None) or {}
    for op in spec.operations:
        out = outputs.get(op.output)
        if not _is_vector(out) or _features(out):
            continue
        refs = list((op.inputs or {}).values())
        if not refs or not _ref_features(refs[0], result, layers):
            continue
        source = _ref_features(refs[0], result, layers)
        lines = [f"مرحلهٔ «{op.op}» ورودی {_fa(len(source))} عارضه‌ای را گرفت و هیچ عارضه‌ای از آن عبور نکرد."]
        conds = _conditions((op.params or {}).get("where"))
        example = ""
        for field, oper, value in conds:
            props = [(f.get("properties") or {}) for f in source if isinstance(f, dict)]
            if not any(field in p for p in props):
                cols = sorted({k for p in props for k in p if not str(k).startswith("_")})
                lines.append(f"ستون «{field}» در داده نیست. ستون‌های موجود: {'، '.join(cols[:25])}")
                continue
            counts: dict[str, int] = {}
            for p in props:
                v = p.get(field)
                counts[str(v)] = counts.get(str(v), 0) + 1
            top = sorted(counts, key=lambda k: -counts[k])[:12]
            example = example or f"{field} آن‌ها «{top[0]}» است"
            lines.append(f"شرط: {field} {oper} «{value}»")
            lines.append(f"مقادیر موجود ستون «{field}»: " + "، ".join(f"«{k}» ({_fa(counts[k])})" for k in top)
                         + (" …" if len(counts) > len(top) else ""))
        if example:
            lines.append(f"پرسش را با یکی از همین مقادیر دقیق دوباره بپرسید؛ مثلاً «… که ستون {example}».")
        elif op.op in SPATIAL_FILTER_OPS:
            target = _ref_features(refs[1], result, layers) if len(refs) > 1 else []
            p = op.params or {}
            dist = p.get("max_distance_m", p.get("max_distance", p.get("distance")))
            if dist is not None:
                lines.append(f"هیچ عارضه‌ای در فاصلهٔ {dist} متری لایهٔ «{refs[1] if len(refs) > 1 else ''}» نبود. "
                             "فاصلهٔ بیشتر را امتحان کنید یا مطمئن شوید هر دو لایه یک محدوده را پوشش می‌دهند.")
            elif _geom_kind(target) == "LineString" and _geom_kind(source) != "LineString":
                lines.append("عارضه‌ها با لایهٔ خطی برخورد مستقیم ندارند (نقطه تقریباً هیچ‌وقت دقیقاً روی خط نیست). "
                             "در پرسش فاصله بدهید؛ مثلاً «در فاصلهٔ ۳۰ متری خیابان‌های اصلی».")
            else:
                lines.append("هیچ عارضه‌ای شرط مکانی را برآورده نکرد؛ محدودهٔ دو لایه یا نوع رابطهٔ خواسته‌شده را بررسی کنید.")
        return lines
    return []


ERROR_HINTS = [
    ("not supported between instances of 'NoneType'",
     "بعضی عارضه‌ها در این مرحله مقدار خالی داشتند و مقایسه نشدند (معمولاً فاصلهٔ عارضه‌هایی که در محدودهٔ جست‌وجو "
     "هیچ هدفی نداشتند)."),
    ("Unsupported operation", "این عملیات در نسخهٔ s3geo نصب‌شده روی سرور وجود ندارد."),
    ("KeyError", "مدل زبانی به ستونی اشاره کرد که در داده نیست."),
    ("CRS", "سیستم مختصات دو لایه با هم نمی‌خواند؛ در پرسش بگویید فاصله‌ها به متر حساب شود."),
]


def _friendly_error(error) -> str:
    text = str(error or "")
    m = re.match(r"Node (\S+) failed: (.*)", text, re.S)
    node, detail = (m.group(1), m.group(2)) if m else ("", text)
    why = next((hint for key, hint in ERROR_HINTS if key in detail), "")
    head = f"مرحلهٔ «{node}» اجرا نشد." if node else "اجرای تحلیل ناموفق بود."
    return " ".join(x for x in (head, why, "پرسش را ساده‌تر یا دقیق‌تر دوباره بپرسید.",
                                f"(جزئیات فنی: {detail.strip()[:250]})") if x)


# ---------------------------------------------------------------------- اعتبارسنجی برنامه با داده
MAX_ENUM = 50  # ستونی که حداکثر این تعداد مقدار متمایز دارد «دسته‌ای» است و مقدارهایش بررسی می‌شود
PRESERVING_OPS = {"filter_attribute", "sort_limit", "crs_transform", "spatial_nearest", "nearest_neighbor",
                  "filter_by_distance", "filter_points_in_polygon", "top_n", "buffer", "centroids", "spatial_join",
                  "area_perimeter", "clip", "intersect", "deduplicate", "repair_geometries", "simplify", "explode"}
VALUE_OPS = {"eq", "ne", "in", "not_in"}


def _profile(layers: dict) -> dict:
    """{لایه: {ستون: مقدارهای متمایز (یا None اگر زیاد/غیرمتنی)}} از خود داده."""
    out = {}
    for name, fc in layers.items():
        cols: dict[str, set | None] = {}
        for f in (fc or {}).get("features") or []:
            for k, v in ((f or {}).get("properties") or {}).items():
                if k not in cols:
                    cols[k] = set()
                seen = cols[k]
                if seen is None or v is None:
                    continue
                if not isinstance(v, str):
                    cols[k] = None
                elif len(seen) > MAX_ENUM:
                    cols[k] = None
                else:
                    seen.add(v.strip())
        out[name] = {k: (None if v is None or len(v) > MAX_ENUM else v) for k, v in cols.items()}
    return out


def _merge_cols(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = None if k in out and (out[k] is None or v is None) else (v if k not in out else out[k] | v)
    return out


def _check_plan(spec, layers: dict) -> list[str]:
    """مشکل‌های برنامه نسبت به داده: ستون ناموجود و مقدار شرطِ ناموجود در ستون دسته‌ای (پیش از اجرا)."""
    avail: dict[str, dict | None] = _profile(layers)
    problems = []
    for op in spec.operations:
        refs = [r for r in (op.inputs or {}).values() if isinstance(r, str)]
        cols: dict | None = {}
        for r in refs:
            c = avail.get(r)
            cols = None if c is None or cols is None else _merge_cols(cols, c)
        params = op.params or {}
        if cols is not None and refs:
            fields = [c[0] for c in _conditions(params.get("where"))]
            fields += [params[k] for k in ("sort_by", "score_field") if isinstance(params.get(k), str)]
            low = {k.lower(): k for k in cols}
            for fld in dict.fromkeys(fields):
                if fld in cols or fld.startswith("_"):
                    continue
                hint = f" Did you mean '{low[fld.lower()]}'?" if fld.lower() in low else ""
                problems.append(f"operation {op.op} -> {op.output}: column '{fld}' does not exist in its input."
                                f"{hint} Existing columns: {', '.join(sorted(k for k in cols if not k.startswith('_')))}.")
            for fld, oper, value in _conditions(params.get("where")):
                values = cols.get(fld)
                if oper not in VALUE_OPS or not values:
                    continue
                wanted = value if isinstance(value, list) else [value]
                bad = [v for v in wanted if isinstance(v, str) and v.strip() not in values]
                if bad:
                    problems.append(f"operation {op.op} -> {op.output}: value(s) {bad} do not exist in column '{fld}'. "
                                    f"The column's exact values are: {sorted(values)}. Use one of these exactly.")
        if op.output:
            avail[op.output] = cols if op.op in PRESERVING_OPS else None
    return problems


# ---------------------------------------------------------------------- اجرا با تلاش دوباره
@dataclass
class Outcome:
    kind: str  # layer | empty | table | answer | failed
    spec: object = None
    result: object = None
    layers: dict = dc_field(default_factory=dict)
    step: str | None = None
    feats: list = dc_field(default_factory=list)
    rows: list = dc_field(default_factory=list)
    error: str = ""
    attempts: int = 1


RANK = {"layer": 4, "table": 4, "answer": 3, "empty": 2, "failed": 1}


def _last_table(result, spec):
    """اگر آخرین مرحله جدول بی‌هندسه است (مثل جمع به تفکیک گروه)، ردیف‌هایش."""
    op = spec.operations[-1]
    out = result.outputs.get(op.output)
    feats = _features(out) if _is_vector(out) else []
    if feats and not any(isinstance(f, dict) and f.get("geometry") for f in feats):
        return op.output, [_clean((f or {}).get("properties")) for f in feats]
    return None, []


def _classify(result, spec, layers) -> Outcome:
    if not result.success:
        return Outcome("failed", spec, result, layers, error=_friendly_error(result.error))
    step, rows = _last_table(result, spec)
    if rows:
        return Outcome("table", spec, result, layers, step=step, rows=rows)
    step, feats = _spatial_output(result, spec)
    if step is not None and not feats:
        return Outcome("empty", spec, result, layers, step=step)
    if feats:
        return Outcome("layer", spec, result, layers, step=step, feats=feats)
    return Outcome("answer", spec, result, layers)


def _retry_note(outcome: Outcome, problems: list[str]) -> str:
    ops = json.dumps([{k: v for k, v in asdict(o).items()} for o in outcome.spec.operations], ensure_ascii=False)[:2500]
    if problems:
        body = "Your previous plan does not match the data:\n- " + "\n- ".join(problems)
    elif outcome.kind == "failed":
        body = f"Your previous plan failed when executed: {outcome.error}"
    else:
        steps = "; ".join(f"{s['op']}({s['name']})={s['count']}" for s in _steps(outcome.result, outcome.spec, outcome.layers)
                          if s["count"] is not None)
        why = " ".join(_why_empty(outcome.result, outcome.spec, outcome.layers))
        body = f"Your previous plan returned ZERO features. Feature counts per step: {steps}. {why}"
    return (f"\n\n[CORRECTION - previous attempt]\nPrevious operations: {ops}\n{body}\n"
            "Return a corrected, complete QuerySpec JSON. Use only real layer names, real column names and the exact "
            "listed values. If the zero result is genuinely the right answer, keep the same plan.")


def _llm_error(exc: Exception) -> str:
    msg = str(exc)
    if "401" in msg or "403" in msg:
        return "کلید مدل زبانی پذیرفته نشد؛ کلید یا اعتبار حساب سرویس را بررسی کنید."
    if "request failed" in msg:
        return "اتصال به سرویس مدل زبانی برقرار نشد؛ آدرس سرویس را بررسی کنید."
    return f"مدل زبانی برنامه تحلیل را نساخت: {msg[:400]}"


def analyze(text: str, layers: dict, client, share_values: bool = True, progress=None) -> Outcome:
    """پرسش فارسی → برنامه s3geo → اجرا؛ با یک اصلاح پیش از اجرا (ستون/مقدار نادرست) و یک اصلاح پس از اجرا
    (نتیجهٔ خالی یا خطا). خطای خود مدل زبانی (کلید، اتصال) در تلاش اول AskError است."""
    import s3geo
    from s3geo import (
        DagExecutor,
        DeterministicPlanner,
        LLMQuerySpecGenerator,
        PlannerConfig,
        RegistryCapabilityResolver,
        derive_input_data_extent,
        describe_input_layers,
    )

    progress = progress or (lambda pct, msg: None)
    extent = derive_input_data_extent(layers)
    described = describe_input_layers(layers)
    generator = LLMQuerySpecGenerator(client, max_repair_attempts=1)
    hints = _hints()
    if share_values:
        hints = f"{hints} {_value_hints(layers)}".strip()
    executor = DagExecutor(RegistryCapabilityResolver(s3geo.registry(tolerant=True)))
    best: Outcome | None = None
    feedback = ""
    pre_retry = post_retry = False
    for attempt in range(1, MAX_ATTEMPTS + 1):
        progress(25 if attempt == 1 else 60, "مدل زبانی برنامه تحلیل را می‌نویسد" if attempt == 1
                 else "مدل زبانی برنامه را اصلاح می‌کند")
        try:
            spec = generator.generate(text + feedback, context={}, system_hints=hints, input_data_extent=extent,
                                      input_layers=described)
        except Exception as exc:  # noqa: BLE001  خطای مدل زبانی (کلید، اینترنت، پاسخ نامعتبر)
            if best is None:
                raise AskError(_llm_error(exc)) from exc
            break
        spec = _patch_spec(spec)
        problems = _check_plan(spec, layers)
        if problems and not pre_retry and attempt < MAX_ATTEMPTS:
            pre_retry = True
            feedback = _retry_note(Outcome("failed", spec, None, layers), problems)
            if best is None:  # برای گزارش اگر تلاش بعدی هم به نتیجه نرسید
                best = Outcome("failed", spec, None, layers, error="برنامهٔ مدل با داده نمی‌خواند: " + problems[0][:300])
            continue
        progress(55, "اجرای مراحل تحلیل")
        try:
            plan = DeterministicPlanner(PlannerConfig(strict_params=True)).build(spec)
            result = executor.execute(plan, initial_inputs=layers)
        except Exception as exc:  # noqa: BLE001  برنامه ساخته شد اما قابل اجرا نبود
            result = _FailedResult(str(exc))
        outcome = _classify(result, spec, layers)
        outcome.attempts = attempt
        if best is None or RANK[outcome.kind] >= RANK[best.kind] or best.result is None:
            best = outcome
        if outcome.kind in ("failed", "empty") and not post_retry and attempt < MAX_ATTEMPTS:
            post_retry = True
            feedback = _retry_note(outcome, [])
            continue
        break
    best.attempts = attempt
    return best


@dataclass
class _FailedResult:  # نتیجهٔ ساختگی وقتی ساخت یا اجرای برنامه استثنا داد
    error: str
    success: bool = False
    outputs: dict = dc_field(default_factory=dict)


# ---------------------------------------------------------------------- نوشتن جدول بدون هندسه
def _sql_type(values: list) -> str:
    vals = [v for v in values if v is not None]
    if vals and all(isinstance(v, bool) for v in vals):
        return "boolean"
    if vals and all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
        return "bigint"
    if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
        return "double precision"
    return "text"


def write_table(conn, name: str, rows: list[dict]) -> int:
    """جدول عمومی (بدون هندسه) با کلید اصلی gid؛ هر ستون با نوع مناسب (عدد، بولی یا متن)."""
    rows = rows[:TABLE_ROW_LIMIT]
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    safe, used = [], {"gid"}
    for c in cols:
        base = (str(c).strip() or "col")[:60]
        n, i = base, 2
        while n.lower() in used:
            n, i = f"{base}_{i}", i + 1
        used.add(n.lower())
        safe.append(n)
    types = [_sql_type([r.get(c) for r in rows]) for c in cols]
    target = sql.Identifier("public", name)
    conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(target))
    conn.execute(sql.SQL("CREATE TABLE {} (gid serial PRIMARY KEY, {})").format(
        target, sql.SQL(", ").join(sql.SQL("{} {}").format(sql.Identifier(n), sql.SQL(t)) for n, t in zip(safe, types, strict=True))))
    ins = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        target, sql.SQL(", ").join(map(sql.Identifier, safe)), sql.SQL(", ").join(sql.Placeholder() for _ in safe))
    data = [tuple((str(r[c]) if t == "text" and r.get(c) is not None else r.get(c)) for c, t in zip(cols, types, strict=True))
            for r in rows]
    with conn.cursor() as cur:
        cur.executemany(ins, data)
    return len(rows)


def run(job: Job, client=None) -> str:
    from databases import gdal

    q = job.question
    db = job.database
    job.set_progress(8, "خواندن لایه‌ها")
    ex = Explorer(db)
    tables = {f"{t.schema}.{t.name}": t for t in ex.tables()}
    layers, notes = {}, list(q.notes or [])
    notes = [n for n in notes if not n.startswith(("برش", "تلاش"))]
    for key in q.layers:
        t = tables.get(key)
        if t is None:
            raise AskError(f"لایه {key} دیگر وجود ندارد.")
        name = t.name if t.schema == "public" else f"{t.schema}_{t.name}"
        layers[name] = json.loads(ex.geojson(t, limit=LAYER_LIMIT))
        n = len(layers[name].get("features") or [])
        if n >= LAYER_LIMIT and (t.rows_estimate or 0) > LAYER_LIMIT:
            notes.append(f"برش: از لایهٔ {name} فقط {n:,} عارضه از حدود {t.rows_estimate:,} خوانده شد؛ نتیجه کامل نیست. "
                         "لایه را کوچک‌تر کنید یا با ابزارهای آماده (بدون سقف) تحلیل کنید.")
    if client is None:
        cfg = LlmConfig.objects.filter(user=q.user).first()
        if cfg is None:
            raise AskError("کلید مدل زبانی پیدا نشد.")
        client = _client(cfg)
    fields = ["goal", "operations", "steps", "result_kind", "answer", "notes", "attempts"]
    try:
        out = analyze(q.text, layers, client, q.share_values, job.set_progress)
    except AskError:
        q.result_kind = Question.Result.FAILED
        q.save(update_fields=["result_kind"])
        raise
    spec = out.spec
    q.goal = spec.goal
    q.operations = [o.op for o in spec.operations]
    q.attempts = out.attempts
    q.steps = _steps(out.result, spec, layers) if out.result is not None else []
    if out.attempts > 1:
        notes.append(f"تلاش {out.attempts}: برنامهٔ مدل یک بار با توجه به داده اصلاح شد.")
    q.notes = notes
    if out.kind == "failed":
        q.result_kind = Question.Result.FAILED
        q.save(update_fields=fields)
        raise AskError(out.error)
    if out.kind == "empty":
        # لایهٔ نتیجه ساخته شد اما خالی است: جدول ساخته نمی‌شود و دلیلش گفته می‌شود
        q.result_kind = Question.Result.EMPTY
        q.answer = "\n".join(_why_empty(out.result, spec, layers))[:MAX_ANSWER_CHARS]
        q.save(update_fields=fields)
        return f"{spec.goal} — هیچ عارضه‌ای پیدا نشد؛ جدول {q.output_table} ساخته نشد"
    if out.kind == "answer":
        # تحلیل درست اجرا شده اما لایه یا جدولی نساخته (عدد، آمار، متن…): این یک پاسخ است، نه خطا
        q.result_kind = Question.Result.ANSWER
        q.answer = _answer_text(out.result, spec)
        q.save(update_fields=fields)
        return f"{spec.goal} — پاسخ متنی (بدون لایه مکانی)"
    job.set_progress(82, "ذخیره نتیجه در جدول")
    if out.kind == "table":
        with ex.connect(read_only=False) as conn:
            conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(db.role_name)))
            n = write_table(conn, q.output_table, out.rows)
        q.result_kind = Question.Result.TABLE
        q.rows = n
        q.answer = ""
        q.save(update_fields=fields + ["rows"])
        return f"{spec.goal} — جدول {q.output_table} با {n:,} ردیف ساخته شد"
    feats = out.feats
    q.result_kind = Question.Result.LAYER
    q.answer = _answer_text(out.result, spec) if out.step != spec.operations[-1].output else ""
    feats = [{"type": "Feature", "geometry": f.get("geometry"), "properties": _clean(f.get("properties"))}
             for f in feats]
    srid = 4326
    if _max_abs_x(feats) > 180:
        from s3geo import derive_input_data_extent
        srid = int(str(derive_input_data_extent(layers).suggested_crs or "EPSG:32639").split(":")[-1])
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "result.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False),
                        encoding="utf-8")
        exists = f"public.{q.output_table}" in tables
        gdal.import_layer(db, path, {"name": "result", "table": q.output_table, "srid": srid, "assign_srid": True,
                                     "to4326": srid != 4326, "mode": "overwrite" if exists else "create",
                                     "geom_type": ""}, "UTF-8")
    q.rows = len(feats)
    q.save(update_fields=fields + ["rows"])
    return f"{spec.goal} — {len(feats):,} عارضه در جدول {q.output_table}"
