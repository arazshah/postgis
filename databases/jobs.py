"""handler کارهای پس‌زمینه‌ی بخش داده (یافتن عارضه، ورود فایل)؛ در plugin.py ثبت می‌شوند."""
import shutil
from pathlib import Path

from django.conf import settings

from jobs.services import JobError
from kernel import tenantdb
from kernel.tenantdb import TenantError

from . import gdal, importinto
from .models import UserDatabase


def do_find(job) -> None:
    """ذخیره‌ی نتیجه‌ی «یافتن عارضه» به‌صورت جدول ثابت یا نمای زنده."""
    from . import find_save
    from .explorer import Explorer
    from .find import Finder

    db = job.database
    ex = Explorer(db)
    job.set_progress(5, "بررسی شرط‌ها")
    plan = find_save.build(Finder(ex), job.params.get("spec"), job.params.get("opts"))
    res = find_save.create(db, ex, plan, step=job.set_progress)
    job.params = {**job.params, "result": res}
    what = "نمای زنده" if res["kind"] == "view" else "لایه"
    job.message = f"{what} {res['table']} با {res['rows']:,} عارضه ساخته شد."


# ---------------------------------------------------------------------- ورود فایل
def import_dir(job) -> Path:
    return Path(settings.IMPORT_ROOT) / str(job.pk)


def do_import(job) -> None:
    db = job.database
    if db.status != UserDatabase.Status.ACTIVE:
        raise JobError("پایگاه داده فعال نیست یا حجمش پر است؛ ورود فایل ممکن نیست.")
    if job.params.get("into"):
        return _do_import_into(job, db)
    path = import_dir(job) / job.params["file"]
    done, errors = [], []
    try:
        for layer in job.params["layers"]:
            if not layer.get("selected"):
                continue
            try:
                gdal.import_layer(db, path, layer, job.params.get("encoding"))
                done.append(layer["table"])
                if layer.get("csv_bad") and layer.get("csv_mode") != "none":
                    bad = str(layer["csv_bad"]).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
                    errors.append(f"{layer['table']}: {bad} سطر مختصات معتبر نداشت و بدون هندسه وارد شد")
            except gdal.GdalError as exc:
                errors.append(f"{layer['name']}: {exc}")
    finally:
        shutil.rmtree(import_dir(job), ignore_errors=True)
    job.params = {**job.params, "imported": done, "errors": errors}
    if not done:
        raise JobError("هیچ لایه‌ای وارد نشد. " + " | ".join(errors))
    count = str(len(done)).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    job.message = f"{count} لایه وارد شد: {'، '.join(done)}" + (f". خطا: {' | '.join(errors)}" if errors else "")


def _do_import_into(job, db) -> None:
    """ورود فایل به جدول موجود: خواندن در جدول موقت، بعد درج (یا جایگزینی) در یک تراکنش همه‌یاهیچ."""
    into = job.params["into"]
    layer = next((x for x in job.params["layers"] if x.get("selected")), None)
    if layer is None:
        raise JobError("لایه‌ای برای ورود انتخاب نشده است.")
    path = import_dir(job) / job.params["file"]
    ex = tenantdb.catalog(db)
    staging = importinto.staging_name(job.pk)
    try:
        try:
            table = ex.find(into["schema"], into["table"])
        except TenantError as exc:
            raise JobError(f"جدول مقصد پیدا نشد: {exc}") from exc
        stage = {"name": layer["name"], "table": staging, "srid": layer.get("srid"),
                 "assign_srid": layer.get("assign_srid"), "to4326": False, "mode": "overwrite", "geom_type": "",
                 "fid": importinto.STAGING_FID, "geom_name": importinto.STAGING_GEOM}
        try:
            gdal.import_layer(db, path, stage, job.params.get("encoding"))
            mapping = {k: int(v) for k, v in (job.params.get("into_map") or {}).items()}
            count = importinto.run_merge(ex, table, mapping, staging, replace=job.params.get("into_mode") == "replace")
        except (gdal.GdalError, TenantError) as exc:
            raise JobError(str(exc)) from exc
    finally:
        importinto.drop_staging(ex, staging)
        shutil.rmtree(import_dir(job), ignore_errors=True)
    fa = str(count).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    verb = "جایگزین شد" if job.params.get("into_mode") == "replace" else "اضافه شد"
    job.params = {**job.params, "imported": [f"{into['schema']}.{into['table']}"], "errors": [], "inserted": count}
    job.message = f"{fa} سطر به «{into['table']}» {verb}."


def expire_import_drafts(now=None) -> int:
    """ورودهای نیمه‌کاره‌ی بیش از یک روز (کاربر فایل را بازبینی نکرد): پوشه‌ی موقت پاک و کار منقضی می‌شود."""
    from datetime import timedelta

    from django.utils import timezone

    from jobs.models import Job

    now = now or timezone.now()
    n = 0
    for job in Job.objects.filter(kind=Job.Kind.IMPORT, status=Job.Status.DRAFT, created_at__lt=now - timedelta(days=1)):
        shutil.rmtree(import_dir(job), ignore_errors=True)
        job.status = Job.Status.EXPIRED
        job.save(update_fields=["status"])
        n += 1
    return n
