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
    generator = LLMQuerySpecGenerator(client, max_repair_attempts=1)
    try:
        spec = generator.generate(q.text, context={}, system_hints="پاسخ و نام ستون‌های جدید می‌تواند فارسی یا لاتین باشد.",
                                  input_data_extent=extent, input_layers=describe_input_layers(layers))
    except Exception as exc:  # noqa: BLE001  خطای مدل زبانی (کلید، اینترنت، پاسخ نامعتبر)
        msg = str(exc)
        if "401" in msg or "403" in msg:
            msg = "کلید مدل زبانی پذیرفته نشد؛ کلید یا اعتبار حساب سرویس را بررسی کنید."
        elif "request failed" in msg:
            msg = "اتصال به سرویس مدل زبانی برقرار نشد؛ آدرس سرویس را بررسی کنید."
        raise AskError(f"مدل زبانی برنامه تحلیل را نساخت: {msg[:400]}") from exc
    q.goal = spec.goal
    q.operations = [o.op for o in spec.operations]
    plan = DeterministicPlanner(PlannerConfig(strict_params=True)).build(spec)
    result = DagExecutor(RegistryCapabilityResolver(s3geo.registry(tolerant=True))).execute(plan, initial_inputs=layers)
    if not result.success:
        q.save(update_fields=["goal", "operations"])
        raise AskError(f"اجرای تحلیل ناموفق بود: {str(result.error)[:400]}")
    out = result.outputs[spec.operations[-1].output]
    feats = [{"type": "Feature", "geometry": f.get("geometry"), "properties": _clean(f.get("properties"))}
             for f in _features(out) if f.get("geometry")]
    if not feats:
        q.save(update_fields=["goal", "operations"])
        return f"{spec.goal} — نتیجه مکانی نداشت: {str(out)[:600]}"
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
    q.save(update_fields=["goal", "operations", "rows"])
    return f"{spec.goal} — {len(feats):,} عارضه در جدول {q.output_table}"
