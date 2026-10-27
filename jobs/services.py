"""
بکاپ، بازگردانی و آزمون بازگردانی پایگاه‌های داده کاربران.

- بکاپ با pg_dump (قالب custom، بدون مالک و دسترسی‌ها) و کاربر ادمین سرور گرفته می‌شود.
- بازگردانی امن است: اول یک بکاپ ایمنی از وضع فعلی، بعد بازگردانی در دیتابیس موقت،
  بررسی سلامت، و فقط در صورت موفقیت جابه‌جایی با دیتابیس اصلی.
- همه این کارها در سرویس worker اجرا می‌شوند (python manage.py run_worker)، نه در درخواست وب.
"""
from __future__ import annotations

import logging
import os
import random
import re
import shutil
import subprocess
from datetime import datetime, time, timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from databases.models import UserDatabase
from databases.provisioner import Provisioner

from .models import Job

log = logging.getLogger(__name__)

MANUAL_PER_DAY = 3
MANUAL_KEEP_DAYS = 7
SAFETY_KEEP_DAYS = 3
NIGHTLY_AT = time(3, 0)  # به وقت تهران
DUMP_TIMEOUT = 3 * 3600


class JobError(Exception):
    pass


def backup_root() -> Path:
    root = Path(settings.BACKUP_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------- صف
def _busy(db: UserDatabase) -> bool:
    return Job.objects.filter(database=db, status__in=[Job.Status.QUEUED, Job.Status.RUNNING],
                              kind__in=[Job.Kind.BACKUP, Job.Kind.RESTORE]).exists()


def request_backup(db: UserDatabase, user) -> Job:
    """بکاپ دستی کاربر (محدود به چند بار در روز)."""
    if db.status not in UserDatabase.LIVE_STATUSES:
        raise JobError("از پایگاه داده غیرفعال نمی‌شود بکاپ گرفت.")
    if _busy(db):
        raise JobError("یک بکاپ یا بازگردانی برای این پایگاه داده در جریان است؛ کمی صبر کنید.")
    since = timezone.now() - timedelta(days=1)
    if Job.objects.filter(database=db, kind=Job.Kind.BACKUP, trigger=Job.Trigger.MANUAL,
                          created_at__gte=since).count() >= MANUAL_PER_DAY:
        raise JobError(f"در هر ۲۴ ساعت حداکثر {MANUAL_PER_DAY} بکاپ دستی می‌توانید بگیرید.")
    return Job.objects.create(kind=Job.Kind.BACKUP, trigger=Job.Trigger.MANUAL, database=db, user=user)


def request_restore(db: UserDatabase, backup: Job, user) -> Job:
    if backup.database_id != db.pk or not backup.downloadable:
        raise JobError("این بکاپ در دسترس نیست.")
    if db.status not in UserDatabase.LIVE_STATUSES:
        raise JobError("پایگاه داده غیرفعال را نمی‌شود بازگردانی کرد.")
    if _busy(db):
        raise JobError("یک بکاپ یا بازگردانی برای این پایگاه داده در جریان است؛ کمی صبر کنید.")
    return Job.objects.create(kind=Job.Kind.RESTORE, trigger=Job.Trigger.MANUAL, database=db, user=user,
                              source=backup)


def claim_next() -> Job | None:
    with transaction.atomic():
        job = (Job.objects.select_for_update(skip_locked=True)
               .filter(status=Job.Status.QUEUED).order_by("created_at").first())
        if job is None:
            return None
        job.status = Job.Status.RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at"])
        return job


def run(job: Job) -> None:
    from iranmap import tasks as iranmap_tasks

    handler = {Job.Kind.BACKUP: _do_backup, Job.Kind.RESTORE: _do_restore,
               Job.Kind.RESTORE_TEST: _do_restore_test, Job.Kind.IMPORT: _do_import,
               Job.Kind.BASEMAP: iranmap_tasks.do_basemap, Job.Kind.OSM_REFRESH: iranmap_tasks.do_osm_refresh,
               Job.Kind.OSM_IMPORT: iranmap_tasks.do_osm_import, Job.Kind.ASK: _do_ask,
               Job.Kind.GEOSERVER: _do_enterprise, Job.Kind.RASTER: _do_enterprise,
               Job.Kind.CLONE: _do_enterprise, Job.Kind.TOOL: _do_tool}[job.kind]
    try:
        handler(job)
    except Exception as exc:  # noqa: BLE001
        log.exception("job %s failed", job.pk)
        job.status = Job.Status.FAILED
        job.message = _clean(str(exc))[:2000]
    else:
        if job.status == Job.Status.RUNNING:
            job.status = Job.Status.DONE
    job.finished_at = timezone.now()
    if job.status == Job.Status.DONE:
        job.progress, job.stage = 100, "تمام شد"
    job.save()


def _do_enterprise(job: Job) -> None:
    from enterprise import services as ent

    fn = {Job.Kind.GEOSERVER: ent.provision, Job.Kind.RASTER: ent.process_raster, Job.Kind.CLONE: ent.do_clone}[job.kind]
    try:
        job.message = fn(job)
    except ent.EnterpriseError as exc:
        raise JobError(str(exc)) from exc


def _do_tool(job: Job) -> None:
    from analysis import tools

    try:
        res = tools.run_job(job)
    except tools.ToolError as exc:
        raise JobError(str(exc)) from exc
    job.message = f"جدول {res['table']} با {res['rows']:,} عارضه ساخته شد."


def _do_ask(job: Job) -> None:
    from analysis import ask

    try:
        job.message = ask.run(job)
    except ask.AskError as exc:
        raise JobError(str(exc)) from exc


def _clean(text: str) -> str:
    """رمز احتمالی را از پیام خطا حذف می‌کند."""
    return re.sub(r"password=\S+", "password=***", text)


# ---------------------------------------------------------------------- ابزار pg_dump / pg_restore
def _tool(name: str) -> str:
    path = shutil.which(name, path=os.environ.get("PG_BIN_PATH") or None) or shutil.which(name)
    if not path:
        raise JobError(f"{name} روی سرور نصب نیست.")
    return path


def _pg_env(server) -> dict:
    kw = server.connection_kwargs()
    return {**os.environ, "PGHOST": str(kw["host"]), "PGPORT": str(kw["port"]), "PGUSER": kw["user"],
            "PGPASSWORD": kw["password"], "PGSSLMODE": kw["sslmode"], "PGCONNECT_TIMEOUT": "15",
            "PGAPPNAME": "geopaygah-backup"}


def _exec(cmd: list[str], env: dict, timeout: int = DUMP_TIMEOUT) -> None:
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise JobError(f"{Path(cmd[0]).name} ناموفق بود: {_clean(proc.stderr.strip())[-1500:]}")


def dump_database(db: UserDatabase, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    try:
        _exec([_tool("pg_dump"), "--format=custom", "--compress=6", "--no-owner", "--no-privileges",
               f"--dbname={db.db_name}", f"--file={tmp}"], _pg_env(db.server))
        tmp.rename(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest.stat().st_size


def restore_into(server, scratch: str, dump: Path) -> None:
    _exec([_tool("pg_restore"), "--no-owner", "--no-privileges", "--exit-on-error",
           f"--dbname={scratch}", str(dump)], _pg_env(server))


def _scratch_name(db_name: str, tag: str) -> str:
    return f"{db_name[:52]}_{tag}"[:63]


# ---------------------------------------------------------------------- اجرای کارها
def _keep_days(job: Job) -> int:
    if job.trigger == Job.Trigger.AUTO:
        return max(1, job.database.plan.backup_retention_days)
    if job.params.get("safety"):
        return SAFETY_KEEP_DAYS
    if job.params.get("archive"):  # بایگانی پایان ترم کلاس
        return 180
    return MANUAL_KEEP_DAYS


def _do_backup(job: Job) -> None:
    db = job.database
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    rel = Path(str(db.pk)) / f"{db.db_name}-{stamp}-{job.trigger}.dump"
    job.size_bytes = dump_database(db, backup_root() / rel)
    job.file = str(rel)
    if job.params.get("snapshot"):
        job.expires_at = timezone.now() + timedelta(hours=settings.SNAPSHOT_KEEP_HOURS)
    else:
        job.expires_at = timezone.now() + timedelta(days=_keep_days(job))
    job.message = "بکاپ کامل گرفته شد."


def _do_restore(job: Job) -> None:
    db, src = job.database, job.source
    if src is None or not src.path or not src.path.exists():
        raise JobError("فایل بکاپ پیدا نشد (ممکن است منقضی شده باشد).")
    # ۱. بکاپ ایمنی از وضع فعلی، تا اگر کاربر پشیمان شد برگردد
    safety = Job.objects.create(kind=Job.Kind.BACKUP, trigger=Job.Trigger.SYSTEM, database=db, user=job.user,
                                params={"safety": True, "before_restore": job.pk},
                                status=Job.Status.RUNNING, started_at=timezone.now())
    run_inline(safety)
    if safety.status != Job.Status.DONE:
        raise JobError(f"بکاپ ایمنی قبل از بازگردانی ناموفق بود؛ چیزی تغییر نکرد. {safety.message}")
    # ۲. بازگردانی در دیتابیس موقت و بررسی سلامت
    prov = Provisioner.for_server(db.server)
    scratch = _scratch_name(db.db_name, "rst")
    prov.create_scratch_database(scratch, db.role_name)
    try:
        restore_into(db.server, scratch, src.path)
        info = prov.finish_restore(scratch, db.role_name)
        # ۳. جابه‌جایی
        old = prov.swap_in_restored(db.db_name, scratch, db.role_name)
    except Exception:
        prov.drop_database(scratch)
        raise
    prov.drop_database(old)
    when = timezone.localtime(src.created_at).strftime("%Y-%m-%d %H:%M")
    job.message = (f"پایگاه داده به بکاپ {when} برگردانده شد ({info['tables']} جدول). "
                   f"نسخه قبلی به‌صورت بکاپ ایمنی تا {SAFETY_KEEP_DAYS} روز نگه داشته می‌شود.")
    job.params = {**job.params, "safety_backup": safety.pk, "tables": info["tables"]}


def _do_restore_test(job: Job) -> None:
    candidates = list(Job.objects.filter(kind=Job.Kind.BACKUP, status=Job.Status.DONE, trigger=Job.Trigger.AUTO,
                                         database__status__in=UserDatabase.LIVE_STATUSES)
                      .order_by("database_id", "-created_at").distinct("database_id"))
    if not candidates:
        job.message = "هنوز بکاپ خودکاری برای آزمون وجود ندارد."
        return
    src = random.choice(candidates)
    db = src.database
    prov = Provisioner.for_server(db.server)
    scratch = _scratch_name(db.db_name, "rtest")
    prov.create_scratch_database(scratch, db.role_name)
    try:
        restore_into(db.server, scratch, src.path)
        info = prov.finish_restore(scratch, db.role_name)
    finally:
        prov.drop_database(scratch)
    job.database = db
    job.source = src
    job.message = f"بکاپ {db.db_name} با موفقیت بازگردانی آزمایشی شد ({info['tables']} جدول)."


# ---------------------------------------------------------------------- ورود فایل
def import_dir(job: Job) -> Path:
    return Path(settings.IMPORT_ROOT) / str(job.pk)


def _do_import(job: Job) -> None:
    from databases import gdal

    db = job.database
    if db.status != UserDatabase.Status.ACTIVE:
        raise JobError("پایگاه داده فعال نیست یا حجمش پر است؛ ورود فایل ممکن نیست.")
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


def run_inline(job: Job) -> Job:
    if job.status == Job.Status.QUEUED:
        job.status, job.started_at = Job.Status.RUNNING, timezone.now()
        job.save(update_fields=["status", "started_at"])
    run(job)
    return job


# ---------------------------------------------------------------------- زمان‌بندی و نگهداری
def schedule_nightly(now: datetime | None = None) -> int:
    """بعد از ساعت ۳ بامداد، برای هر پایگاه داده فعال که امروز بکاپ خودکار ندارد، بکاپ در صف می‌گذارد."""
    now = timezone.localtime(now or timezone.now())
    if now.time() < NIGHTLY_AT:
        return 0
    start = now.replace(hour=NIGHTLY_AT.hour, minute=NIGHTLY_AT.minute, second=0, microsecond=0)
    done_today = set(Job.objects.filter(kind=Job.Kind.BACKUP, trigger=Job.Trigger.AUTO, created_at__gte=start)
                     .values_list("database_id", flat=True))
    count = 0
    for db in UserDatabase.objects.filter(status__in=UserDatabase.LIVE_STATUSES).exclude(pk__in=done_today):
        Job.objects.create(kind=Job.Kind.BACKUP, trigger=Job.Trigger.AUTO, database=db)
        count += 1
    return count


def schedule_restore_test(now: datetime | None = None) -> bool:
    now = now or timezone.now()
    if Job.objects.filter(kind=Job.Kind.RESTORE_TEST, created_at__gte=now - timedelta(days=7)).exists():
        return False
    Job.objects.create(kind=Job.Kind.RESTORE_TEST, trigger=Job.Trigger.SYSTEM)
    return True


def cleanup(now: datetime | None = None) -> int:
    """فایل‌های منقضی را پاک و کارهای گیرکرده را ناموفق علامت می‌زند."""
    now = now or timezone.now()
    removed = 0
    for job in Job.objects.filter(status=Job.Status.DONE, expires_at__lt=now).exclude(file=""):
        if job.path:
            job.path.unlink(missing_ok=True)
        job.status = Job.Status.EXPIRED
        job.save(update_fields=["status"])
        removed += 1
    # بکاپ‌های پایگاه داده‌های حذف‌شده
    for job in Job.objects.filter(status=Job.Status.DONE, database__status=UserDatabase.Status.DELETED):
        if job.path:
            job.path.unlink(missing_ok=True)
        job.status = Job.Status.EXPIRED
        job.save(update_fields=["status"])
        removed += 1
    for job in Job.objects.filter(kind=Job.Kind.IMPORT, status=Job.Status.DRAFT, created_at__lt=now - timedelta(days=1)):
        shutil.rmtree(import_dir(job), ignore_errors=True)
        job.status = Job.Status.EXPIRED
        job.save(update_fields=["status"])
    Job.objects.filter(status=Job.Status.RUNNING, started_at__lt=now - timedelta(seconds=DUMP_TIMEOUT + 600)).update(
        status=Job.Status.FAILED, message="کار بیش از حد طول کشید یا worker متوقف شد.", finished_at=now)
    return removed


def disk_usage() -> dict:
    u = shutil.disk_usage(backup_root())
    return {"total": u.total, "used": u.used, "free": u.free, "percent": round(u.used / u.total * 100, 1)}


_last_disk_alert: datetime | None = None


def alerts() -> list[str]:
    """هشدارهای مدیر: بکاپ/بازگردانی ناموفق و پر شدن دیسک. هر کار ناموفق فقط یک بار اعلام می‌شود."""
    from core.alerts import notify_admins

    lines = []
    failed = list(Job.objects.filter(status=Job.Status.FAILED, alerted=False).select_related("database"))
    for job in failed:
        lines.append(f"{job.get_kind_display()} {job.database or ''} ناموفق: {job.message[:120]}")
    global _last_disk_alert
    disk = disk_usage()
    now = timezone.now()
    if disk["percent"] >= 85 and (_last_disk_alert is None or now - _last_disk_alert > timedelta(hours=12)):
        lines.append(f"دیسک بکاپ {disk['percent']}٪ پر است.")
        _last_disk_alert = now
    if lines:
        notify_admins("هشدار بکاپ", "\n".join(lines))
        Job.objects.filter(pk__in=[j.pk for j in failed]).update(alerted=True)
    return lines


def tick(now: datetime | None = None) -> dict:
    """کارهای دوره‌ای worker (هر دقیقه)."""
    from classroom import services as classroom_services
    from enterprise import services as ent
    from iranmap import tasks as iranmap_tasks

    ent.cleanup_rasters_dir()

    return {"classes": classroom_services.tick(now), "nightly": schedule_nightly(now),
            "restore_test": schedule_restore_test(now),
            "cleanup": cleanup(now), "alerts": len(alerts()), "map_data": iranmap_tasks.schedule(now),
            "snapshots": ent.schedule_snapshots(now)}
