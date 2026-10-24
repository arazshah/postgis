"""
پرسش فارسی از داده با s3geo و کلید مدل زبانی خود کاربر.

به مدل زبانی فقط «توصیف» لایه‌ها می‌رود (نام، ستون‌ها، نوع هندسه، تعداد، محدوده)؛ خود عوارض روی همین سرور
پردازش می‌شوند. نتیجه به‌صورت جدول جدید در پایگاه داده کاربر ذخیره می‌شود.
"""
from __future__ import annotations

import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.utils import timezone

from databases.explorer import Explorer
from databases.gdal import TABLE_RE
from jobs.models import Job

from .models import LlmConfig, Question

LAYER_LIMIT = 5000
MAX_LAYERS = 4
DAILY_LIMIT = 40


class AskError(Exception):
    pass


def request(db, user, text: str, layer_keys: list[str], output: str) -> Question:
    text = (text or "").strip()
    if len(text) < 8:
        raise AskError("پرسش را کامل‌تر بنویسید.")
    if not LlmConfig.objects.filter(user=user).exists():
        raise AskError("اول کلید مدل زبانی خود را وارد کنید.")
    output = (output or "").strip().lower()
    if not TABLE_RE.match(output):
        raise AskError("نام جدول نتیجه: حروف کوچک لاتین، رقم و _ (مثلاً schools_far_from_metro).")
    tables = {f"{t.schema}.{t.name}": t for t in Explorer(db).tables()}
    layer_keys = [k for k in dict.fromkeys(layer_keys) if k in tables and tables[k].geometry]
    if not layer_keys:
        raise AskError("دست‌کم یک لایه مکانی انتخاب کنید.")
    if len(layer_keys) > MAX_LAYERS:
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
                                   job=job)


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
    return text.strip()


# ---------------------------------------------------------------------- برداشت نتیجه
def _spatial_output(result, spec):
    """آخرین خروجی مرحله‌ها که عارضهٔ دارای هندسه دارد؛ از آخر به اول (مرحلهٔ خلاصه‌ساز آخر نباید نتیجه را از بین ببرد)."""
    for op in reversed(spec.operations):
        out = result.outputs.get(op.output)
        feats = [f for f in _features(out) if isinstance(f, dict) and f.get("geometry")]
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


def run(job: Job, client=None) -> str:
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

    from databases import gdal

    q = job.question
    db = job.database
    job.set_progress(8, "خواندن لایه‌ها")
    ex = Explorer(db)
    tables = {f"{t.schema}.{t.name}": t for t in ex.tables()}
    layers = {}
    for key in q.layers:
        t = tables.get(key)
        if t is None:
            raise AskError(f"لایه {key} دیگر وجود ندارد.")
        name = t.name if t.schema == "public" else f"{t.schema}_{t.name}"
        layers[name] = json.loads(ex.geojson(t, limit=LAYER_LIMIT))
    if client is None:
        cfg = LlmConfig.objects.filter(user=q.user).first()
        if cfg is None:
            raise AskError("کلید مدل زبانی پیدا نشد.")
        client = _client(cfg)
    extent = derive_input_data_extent(layers)
    job.set_progress(25, "مدل زبانی برنامه تحلیل را می‌نویسد")
    generator = LLMQuerySpecGenerator(client, max_repair_attempts=1)
    try:
        spec = generator.generate(q.text, context={}, system_hints=_hints(),
                                  input_data_extent=extent, input_layers=describe_input_layers(layers))
    except Exception as exc:  # noqa: BLE001  خطای مدل زبانی (کلید، اینترنت، پاسخ نامعتبر)
        msg = str(exc)
        if "401" in msg or "403" in msg:
            msg = "کلید مدل زبانی پذیرفته نشد؛ کلید یا اعتبار حساب سرویس را بررسی کنید."
        elif "request failed" in msg:
            msg = "اتصال به سرویس مدل زبانی برقرار نشد؛ آدرس سرویس را بررسی کنید."
        raise AskError(f"مدل زبانی برنامه تحلیل را نساخت: {msg[:400]}") from exc
    job.set_progress(55, "اجرای مراحل تحلیل")
    q.goal = spec.goal
    q.operations = [o.op for o in spec.operations]
    plan = DeterministicPlanner(PlannerConfig(strict_params=True)).build(spec)
    result = DagExecutor(RegistryCapabilityResolver(s3geo.registry(tolerant=True))).execute(plan, initial_inputs=layers)
    if not result.success:
        q.save(update_fields=["goal", "operations"])
        raise AskError(f"اجرای تحلیل ناموفق بود: {str(result.error)[:400]}")
    step, feats = _spatial_output(result, spec)
    if not feats:
        # تحلیل درست اجرا شده اما لایه‌ای نساخته (عدد، آمار، متن…): این یک پاسخ است، نه خطا
        q.answer = _answer_text(result, spec)
        q.save(update_fields=["goal", "operations", "answer"])
        return f"{spec.goal} — پاسخ متنی (بدون لایه مکانی)"
    if step != spec.operations[-1].output:
        q.answer = _answer_text(result, spec)  # خلاصهٔ مرحلهٔ آخر کنار لایه نمایش داده می‌شود
    feats = [{"type": "Feature", "geometry": f.get("geometry"), "properties": _clean(f.get("properties"))}
             for f in feats]
    job.set_progress(82, "ذخیره نتیجه در جدول")
    srid = 4326
    if _max_abs_x(feats) > 180:
        srid = int(str(extent.suggested_crs or "EPSG:32639").split(":")[-1])
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "result.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False),
                        encoding="utf-8")
        exists = f"public.{q.output_table}" in tables
        gdal.import_layer(db, path, {"name": "result", "table": q.output_table, "srid": srid, "assign_srid": True,
                                     "to4326": srid != 4326, "mode": "overwrite" if exists else "create",
                                     "geom_type": ""}, "UTF-8")
    q.rows = len(feats)
    q.save(update_fields=["goal", "operations", "rows", "answer"])
    return f"{spec.goal} — {len(feats):,} عارضه در جدول {q.output_table}"
