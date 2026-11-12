"""نماهای «ورود فایل» (جدول تازه یا درون جدول موجود)."""

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.decorators import site_user_required
from databases import csvgeo
from databases.explorer import ExplorerError
from databases.models import UserDatabase
from kernel import tenantdb, workspace

from . import importinto

# ---------------------------------------------------------------------- ورود CSV: ستون‌های مکانی
CSV_MODES = [
    ("xy", "دو ستون جدا: طول (X) و عرض (Y)"),
    ("pair", "یک ستون با هر دو مقدار (مثل «35.7, 51.4»)"),
    ("wkt", "ستون هندسه به‌صورت WKT"),
    ("none", "بدون مکان (فقط جدول)"),
]


def _import_job(db, job_id):
    from jobs.models import Job

    return get_object_or_404(db.jobs, pk=job_id, kind=Job.Kind.IMPORT)


@site_user_required
@require_http_methods(["GET", "POST"])
def import_start(request, pk):
    import shutil
    from pathlib import Path

    from databases import gdal
    from jobs.models import Job

    from .jobs import import_dir

    db, ex = workspace.open_catalog(request, pk, "editor")
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    max_mb = settings.IMPORT_MAX_MB
    error = None
    into_ref = (request.POST.get("into") or request.GET.get("into") or "").strip()
    into = None
    if into_ref:
        try:
            schema, _, name = into_ref.partition(".")
            into = ex.find(schema, name)
            if into.kind not in tenantdb.WRITABLE_KINDS:
                raise ExplorerError("فقط در جدول معمولی می‌شود داده وارد کرد (نه نما).")
        except ExplorerError as exc:
            into, error = None, str(exc)
            messages.error(request, str(exc))
            return redirect("databases:explore", pk=db.pk)
    if request.method == "POST":
        f = request.FILES.get("file")
        ext = Path(f.name).suffix.lower() if f else ""
        free = max(0, db.quota_bytes - db.size_bytes)
        if db.status != UserDatabase.Status.ACTIVE:
            error = "پایگاه داده فقط‌خواندنی یا غیرفعال است؛ ورود داده ممکن نیست."
        elif not f:
            error = "فایلی انتخاب نشده است."
        elif ext not in gdal.ALLOWED_EXT:
            error = "این قالب پشتیبانی نمی‌شود. Shapefile را zip کنید؛ یا GeoPackage، GeoJSON، KML، CSV و DXF بفرستید."
        elif f.size > max_mb * 1024 * 1024:
            error = f"حجم فایل بیشتر از {max_mb} مگابایت است."
        elif f.size * (2.6 if into else 1.3) > free:
            error = "فضای خالی پایگاه داده برای این فایل کافی نیست. پلن را ارتقا دهید یا داده‌های اضافه را حذف کنید."
        else:
            job = Job.objects.create(kind=Job.Kind.IMPORT, status=Job.Status.DRAFT, database=db, user=request.user,
                                     params={"file": f"upload{ext}", "original": f.name[:200]})
            folder = import_dir(job)
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / f"upload{ext}", "wb") as out:
                for chunk in f.chunks():
                    out.write(chunk)
            existing = {t.name for t in ex.tables() if t.schema == "public"}
            try:
                if ext == ".csv":
                    info = _csv_start(job, folder, existing)
                else:
                    info = gdal.inspect(folder / f"upload{ext}")
            except (gdal.GdalError, ValueError) as exc:
                shutil.rmtree(folder, ignore_errors=True)
                job.delete()
                error = f"فایل خوانده نشد: {exc}"
            else:
                for lyr in info["layers"]:
                    if ext == ".csv":
                        continue  # لایه CSV در _csv_start کامل ساخته شده است
                    lyr["selected"] = bool(lyr["geom_type"] or ext == ".csv")
                    lyr["exists"] = lyr["table"] in existing
                    lyr["mode"] = "create"
                    lyr["to4326"] = False
                job.params = {**job.params, **info}
                if into:
                    _into_init(job, ex, into)
                job.save(update_fields=["params"])
                return redirect("databases:import_review", pk=db.pk, job_id=job.pk)
    recent = db.jobs.filter(kind="import").exclude(status="draft")[:10]
    return render(request, "databases/import.html", {
        "db": db, "tables": ex.tables(), "section": "import", "error": error, "max_mb": max_mb,
        "accept": ",".join(sorted(gdal.ALLOWED_EXT)), "recent": recent, "into": into})


@site_user_required
@require_http_methods(["GET", "POST"])
def import_review(request, pk, job_id):
    from databases import gdal
    from jobs.models import Job

    from .jobs import import_dir

    db, ex = workspace.open_catalog(request, pk, "editor")
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    job = _import_job(db, job_id)
    layers = job.params.get("layers", [])
    errors = []
    if request.method == "POST" and job.status == Job.Status.DRAFT:
        if request.POST.get("action") == "cancel":
            import shutil

            shutil.rmtree(import_dir(job), ignore_errors=True)
            job.delete()
            return redirect("databases:import", pk=db.pk)
        if request.POST.get("action") == "pick" and job.params.get("into"):
            # لایه‌ی دیگری از فایل انتخاب شد: نگاشت خودکار از نو ساخته می‌شود
            try:
                idx = int(request.POST.get("layer_into", "0"))
            except ValueError:
                idx = 0
            idx = idx if 0 <= idx < len(layers) else 0
            for i, lyr in enumerate(layers):
                lyr["selected"] = i == idx
            job.params["layers"] = layers
            job.params["into_map"] = importinto.auto_map(ex.columns(_into_table(ex, job)), layers[idx].get("fields", []))
            job.save(update_fields=["params"])
            return redirect("databases:import_review", pk=db.pk, job_id=job.pk)
        enc = request.POST.get("encoding") or None
        if job.params.get("csv"):
            try:
                errors += _csv_update(job, request.POST, enc, {t.name for t in ex.tables() if t.schema == "public"})
            except (gdal.GdalError, ValueError) as exc:
                errors.append(f"فایل با این تنظیمات خوانده نشد: {exc}")
            layers = job.params["layers"]
            if request.POST.get("action") == "resample" and not errors:
                job.save(update_fields=["params"])
                return redirect("databases:import_review", pk=db.pk, job_id=job.pk)
        elif job.params.get("encoding") and enc in ("UTF-8", "CP1256") and enc != job.params["encoding"]:
            job.params["encoding"] = enc
            path = import_dir(job) / job.params["file"]
            for lyr in layers:
                lyr["sample"] = gdal.sample(path, lyr["name"], enc)
            job.save(update_fields=["params"])
            if request.POST.get("action") == "resample":
                return redirect("databases:import_review", pk=db.pk, job_id=job.pk)
        into = job.params.get("into")
        if into:
            names = _into_post(request.POST, job, ex, layers, errors)
        else:
            existing = {t.name for t in ex.tables() if t.schema == "public"}
            names = []
            for i, lyr in enumerate(layers):
                lyr["selected"] = request.POST.get(f"sel_{i}") == "on"
                lyr["table"] = (request.POST.get(f"table_{i}") or lyr["table"]).strip().lower()
                lyr["mode"] = request.POST.get(f"mode_{i}", "create")
                lyr["to4326"] = request.POST.get(f"to4326_{i}") == "on"
                srid = request.POST.get(f"srid_{i}") or ""
                lyr["assign_srid"] = bool(srid) and (not lyr.get("srid") or int(srid) != lyr["srid"])
                lyr["srid"] = int(srid) if srid.isdigit() else lyr.get("srid")
                if not lyr["selected"]:
                    continue
                if not gdal.TABLE_RE.match(lyr["table"]):
                    errors.append(f"نام جدول «{lyr['table']}» مجاز نیست: فقط حروف کوچک انگلیسی، عدد و _، شروع با حرف.")
                elif lyr["table"] in names:
                    errors.append(f"نام جدول «{lyr['table']}» دو بار انتخاب شده است.")
                elif lyr["table"] in existing and lyr["mode"] == "create":
                    errors.append(f"جدول «{lyr['table']}» از قبل وجود دارد؛ نام دیگری بدهید یا «جایگزینی» یا «افزودن» را انتخاب کنید.")
                if lyr["geom_type"] and not lyr["srid"]:
                    errors.append(f"سیستم مختصات لایه «{lyr['name']}» مشخص نیست؛ آن را انتخاب کنید.")
                if "csv_bad" in lyr:
                    errors += _csv_checks(lyr)
                names.append(lyr["table"])
            if not names:
                errors.append("حداقل یک لایه را انتخاب کنید.")
        job.params["layers"] = layers
        if errors:
            job.save(update_fields=["params"])
        else:
            job.status = Job.Status.QUEUED
            job.created_at = timezone.now()
            job.save(update_fields=["params", "status", "created_at"])
            from analytics import services as analytics
            from analytics.models import Event

            analytics.record(request, Event.IMPORT_QUEUED, ext=str(job.params.get("file", "")).rsplit(".", 1)[-1])
            messages.success(request, "ورود فایل در صف قرار گرفت.")
            return redirect("databases:import_review", pk=db.pk, job_id=job.pk)
    known = {code for code, _ in gdal.SRID_CHOICES}
    for lyr in layers:
        lyr["srid_in_list"] = lyr.get("srid") in known
        if "csv_bad" in lyr:
            lyr["csv_warn"] = csvgeo.range_check(lyr.get("csv_stats") or {}, lyr.get("srid"))[1]
    csv_info = job.params.get("csv")
    into_ctx = _into_context(ex, job, layers) if job.params.get("into") else None
    return render(request, "databases/import_review.html", {
        "db": db, "tables": ex.tables(), "section": "import", "job": job, "layers": layers, "errors": errors,
        "into": into_ctx,
        "srid_choices": gdal.SRID_CHOICES, "csv": csv_info, "csv_modes": CSV_MODES,
        "csv_encodings": list(csvgeo.ENCODINGS)})


# ---------------------------------------------------------------------- ورود فایل به جدول موجود (نگاشت ستون‌ها)
def _into_init(job, ex, table) -> None:
    layers = job.params["layers"]
    pick = next((x for x in layers if x.get("geom_type")), layers[0])
    for x in layers:
        x["selected"] = x is pick
    job.params["into"] = {"schema": table.schema, "table": table.name}
    job.params["into_map"] = importinto.auto_map(ex.columns(table), pick.get("fields", []))
    job.params["into_mode"] = "append"


def _into_table(ex, job):
    into = job.params["into"]
    return ex.find(into["schema"], into["table"])


def _into_context(ex, job, layers) -> dict:
    t = _into_table(ex, job)
    cols = ex.columns(t)
    layer = next((x for x in layers if x.get("selected")), layers[0] if layers else {})
    fields = layer.get("fields", [])
    mapping = job.params.get("into_map") or {}
    sample = (layer.get("sample") or [{}])[0]
    rows = []
    for c in importinto.target_columns(cols):
        i = mapping.get(c["name"])
        src = fields[i] if isinstance(i, int) and 0 <= i < len(fields) else None
        rows.append({"col": c, "required": importinto.is_required(c), "src": i, "src_name": src,
                     "sample": "" if src is None else sample.get(src, "")})
    geo = next(iter(t.geometry), None)
    gcol = next((c for c in cols if geo and c["name"] == geo["column"]), None)
    compat = importinto.geom_compat(layer.get("geom_type") or "", (geo or {}).get("type") or "")
    return {"table": t, "rows": rows, "fields": list(enumerate(fields)), "geo": geo,
            "geo_required": bool(gcol and gcol["not_null"]), "geom_ok": compat,
            "mode": job.params.get("into_mode", "append"), "layer": layer, "count": layer.get("count"),
            "same_srid": bool(geo and layer.get("srid") and layer["srid"] == geo["srid"])}


def _into_post(post, job, ex, layers, errors) -> list:
    """فرم نگاشت ستون‌ها را اعتبارسنجی و در params ذخیره می‌کند؛ خطاها به errors اضافه می‌شوند."""
    t = _into_table(ex, job)
    cols = ex.columns(t)
    try:
        pick = int(post.get("layer_into", "0"))
    except ValueError:
        pick = 0
    pick = pick if 0 <= pick < len(layers) else 0
    for i, lyr in enumerate(layers):
        lyr["selected"] = i == pick
    lyr = layers[pick]
    srid = post.get(f"srid_{pick}") or ""
    lyr["assign_srid"] = bool(srid) and (not lyr.get("srid") or int(srid) != lyr["srid"])
    lyr["srid"] = int(srid) if srid.isdigit() else lyr.get("srid")
    fields = lyr.get("fields", [])
    mapping = {}
    for c in importinto.target_columns(cols):
        raw = post.get("map_" + c["name"], "")
        if raw == "":
            if importinto.is_required(c):
                errors.append(f"ستون «{c['name']}» الزامی است و مقدار پیش‌فرض ندارد؛ یک ستون فایل برایش انتخاب کنید.")
            continue
        if not raw.isdigit() or int(raw) >= len(fields):
            errors.append(f"ستون فایل برای «{c['name']}» نامعتبر است.")
            continue
        mapping[c["name"]] = int(raw)
    job.params["into_map"] = mapping
    mode = post.get("into_mode", "append")
    job.params["into_mode"] = mode if mode in ("append", "replace") else "append"
    geo = next(iter(t.geometry), None)
    if geo:
        if not lyr.get("geom_type"):
            gcol = next((c for c in cols if c["name"] == geo["column"]), None)
            if gcol and gcol["not_null"]:
                errors.append(f"ستون هندسه‌ی «{geo['column']}» الزامی است ولی این فایل هندسه ندارد.")
        else:
            if not lyr.get("srid"):
                errors.append("سیستم مختصات فایل مشخص نیست؛ آن را انتخاب کنید.")
            if not importinto.geom_compat(lyr.get("geom_type"), geo.get("type")):
                errors.append(f"نوع هندسه‌ی فایل ({lyr['geom_type']}) با ستون «{geo['column']}» ({geo['type']}) نمی‌خواند.")
    if not mapping and not (geo and lyr.get("geom_type")):
        errors.append("دست‌کم یک ستون را به ستونی از فایل وصل کنید.")
    if job.params["into_mode"] == "replace" and post.get("confirm", "").strip() != t.name:
        errors.append("برای جایگزینی کل داده‌ها، نام جدول را دقیقاً در کادر تأیید بنویسید.")
    if "csv_bad" in lyr:
        errors += _csv_checks(lyr)
    return [t.name]


def _csv_start(job, folder, existing: set) -> dict:
    """بعد از آپلود CSV: تحلیل، پیشنهاد ستون‌ها، بازنویسی و ساخت لایه."""
    src = folder / job.params["file"]
    job.params["source"] = job.params["file"]
    job.params["csv"] = csvgeo.analyze(src)
    lyr = _csv_refresh(job, folder, existing, None)
    return {"driver": "CSV", "encoding": job.params["csv"]["encoding"], "layers": [lyr]}


def _csv_refresh(job, folder, existing: set, prev: dict | None) -> dict:
    """فایل را با spec فعلی آماده می‌کند و لایه را می‌سازد؛ انتخاب‌های قبلی کاربر (نام جدول، حالت، SRID) حفظ می‌شود."""
    from databases import gdal

    info = job.params["csv"]
    spec = info["spec"]
    dst = csvgeo.prepared_path(folder, job.params.get("original", ""))
    stats = csvgeo.prepare(folder / job.params["source"], dst, info["encoding"], info["delimiter"], spec)
    job.params["file"] = str(dst.relative_to(folder))
    lyr = gdal.inspect(dst)["layers"][0]
    lyr["sample"] = []  # برای CSV نمونه خام فایل در بخش ستون‌ها نمایش داده می‌شود
    guess = stats.get("srid") or spec.get("srid") or csvgeo.guess_srid(stats)
    keep_srid = prev and prev.get("srid") and prev.get("csv_mode") == spec["mode"]
    srid = prev["srid"] if keep_srid else guess
    if spec["mode"] == "none":
        srid = None
    lyr.update({
        "srid": srid, "selected": True, "mode": "create", "to4326": False,
        "csv_mode": spec["mode"], "csv_bad": stats["bad"], "csv_rows": stats["rows"],
        "csv_stats": {k: stats[k] for k in ("xmin", "xmax", "ymin", "ymax", "points")},
    })
    if prev:
        lyr.update({k: prev[k] for k in ("table", "mode", "to4326", "selected") if k in prev})
    lyr["exists"] = lyr["table"] in existing
    return lyr


def _csv_update(job, post, enc: str | None, existing: set) -> list[str]:
    """تغییر انکودینگ یا ستون‌های مکانی از فرم بررسی؛ فقط در صورت تغییر، فایل دوباره ساخته می‌شود."""
    from .jobs import import_dir

    folder = import_dir(job)
    info = job.params["csv"]
    prev = (job.params.get("layers") or [None])[0]
    if enc in csvgeo.ENCODINGS and enc != info["encoding"]:
        # نام ستون‌ها با انکودینگ دیگر عوض می‌شود؛ تحلیل از نو
        job.params["csv"] = csvgeo.analyze(folder / job.params["source"], enc)
        job.params["encoding"] = enc
    else:
        spec, errors = csvgeo.clean_spec(info["columns"], {
            "mode": post.get("csv_mode"), "x": post.get("csv_x"), "y": post.get("csv_y"),
            "pair": post.get("csv_pair"), "pair_order": post.get("csv_pair_order"), "geom": post.get("csv_geom")})
        if errors:
            return errors
        if csvgeo.same_spec(spec, info["spec"]):
            return []
        info["spec"] = {**spec, "srid": None}
    job.params["layers"] = [_csv_refresh(job, folder, existing, prev)]
    return []


def _csv_checks(lyr: dict) -> list[str]:
    if lyr.get("csv_mode") == "none":
        return []
    if lyr.get("csv_rows") and lyr["csv_bad"] >= lyr["csv_rows"]:
        return ["در هیچ سطری مختصات قابل‌خواندن پیدا نشد. ستون‌های مکانی را درست انتخاب کنید یا «بدون مکان» را بزنید."]
    level, msg = csvgeo.range_check(lyr.get("csv_stats") or {}, lyr.get("srid"))
    return [msg] if level == "error" else []
