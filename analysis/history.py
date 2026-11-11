"""تاریخچهٔ یکپارچهٔ تحلیل‌ها: ردیف‌های پرسش فارسی و اجرای ابزار برای کارت‌ها و مودال جزئیات."""
from urllib.parse import urlencode

from django.urls import reverse

from kernel.plugins import registry

from .models import Question, ToolRun

HISTORY_LIMIT = 24
# نام فارسی مرحله‌های رایج برنامهٔ s3geo در گزارش مرحله‌به‌مرحلهٔ پرسش
OP_LABELS = {
    "input": "ورودی", "crs_transform": "تبدیل مختصات", "filter_attribute": "فیلتر ستونی", "sort_limit": "مرتب‌سازی",
    "spatial_nearest": "نزدیک‌ترین", "nearest_neighbor": "نزدیک‌ترین", "filter_by_distance": "فیلتر فاصله",
    "spatial_join": "اتصال مکانی", "filter_points_in_polygon": "نقطه در چندضلعی", "buffer": "حریم",
    "summarize_vector": "خلاصه", "attribute_statistics": "آمار ستونی", "top_n": "برترین‌ها", "dissolve": "ادغام",
    "area_perimeter": "طول و مساحت", "calculate_field": "محاسبه ستون", "distance_to": "فاصله",
}
def together(db, output: str, inputs) -> str:
    """«نمایش با هم»: نتیجه بالای لایه‌های ورودی (بدون ذخیره نقشه)."""
    keys = [f"public.{output}"] + [k for k in (inputs or []) if isinstance(k, str) and k]
    keys = list(dict.fromkeys(keys))
    if len(keys) < 2:
        return ""
    return reverse("maps:quick", args=[db.pk]) + "?" + urlencode([("t", k) for k in keys])


def entries(db, kinds=("tool", "ask"), limit=HISTORY_LIMIT):
    """تاریخچه، تازه‌ترین اول. kinds: «tool» و/یا «ask»."""
    out = []
    if "tool" in kinds:
        for r in ToolRun.objects.filter(database=db).select_related("job")[:limit]:
            t = registry.get("tool", r.tool)  # ابزار پلاگین است؛ تحلیل آن را فقط از رجیستری هسته می‌شناسد
            out.append({"kind": "tool", "id": f"t{r.pk}", "tool": r.tool, "title": t.title if t else r.tool,
                        "icon": t.icon if t else "toolbox", "detail": r.summary, "table": r.output_table, "rows": r.rows,
                        "job": r.job, "created": r.created_at, "chart": t.chart_hint if t else None,
                        "together": together(db, r.output_table, [r.params.get("layer"), r.params.get("other")])})
    if "ask" in kinds:
        for q in Question.objects.filter(database=db).select_related("job")[:limit]:
            steps = [{**s, "label": OP_LABELS.get(s.get("op"), s.get("op"))} for s in q.steps or []]
            out.append({"kind": "ask", "id": f"q{q.pk}", "pk": q.pk, "title": q.text, "icon": "spark", "detail": q.goal,
                        "ops": q.operations, "steps": steps, "result": q.result_kind, "notes": q.notes,
                        "plan_text": q.plan_text, "summary": q.summary, "preview": q.preview,
                        "followable": q.result_kind == "layer", "answer": q.answer, "table": q.output_table,
                        "rows": q.rows, "job": q.job, "created": q.created_at,
                        "together": together(db, q.output_table, q.layers)})
    out.sort(key=lambda e: e["created"], reverse=True)
    out = out[:limit]
    for e in out:
        e["state"] = state(e)
    return out


def state(e) -> str:
    """وضعیت نمایشی کارت: running | failed | plan | empty | done."""
    j = e["job"]
    if j is None:
        return "failed"
    if j.status in ("queued", "running"):
        return "running"
    if j.status == "failed":
        return "failed"
    if e["kind"] == "ask":
        if e["result"] == "plan":
            return "plan"
        if e["result"] == "empty":
            return "empty"
    return "done"
