"""خدمات پلن سازمانی: GeoServer اختصاصی، رستر، کپی پایگاه داده، بکاپ ساعتی."""
from __future__ import annotations

import json
import logging
import subprocess
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from databases.models import DbRole, UserDatabase
from jobs.models import Job

from . import geoserver
from .models import GeoServerInstance, Raster

log = logging.getLogger(__name__)
RASTER_EXT = {".tif", ".tiff", ".gtiff"}
# امضای واقعی TIFF و BigTIFF؛ تا فایلی با پسوند tif ولی از نوع VRT (که می‌تواند فایل‌های دیگر سرور را بخواند) رد شود
TIFF_MAGIC = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")


MAX_CLONES = 2


class EnterpriseError(Exception):
    pass


# ---------------------------------------------------------------------- GeoServer اختصاصی
def request_geoserver(db: UserDatabase, user) -> GeoServerInstance:
    if not db.plan.dedicated_geoserver:
        raise EnterpriseError("GeoServer اختصاصی فقط در پلن سازمانی است.")
    if not db.is_live:
        raise EnterpriseError("پایگاه داده فعال نیست.")
    inst, created = GeoServerInstance.objects.get_or_create(database=db, defaults={"requested_by": user})
    if not created and inst.status not in (GeoServerInstance.Status.FAILED, GeoServerInstance.Status.STOPPED):
        raise EnterpriseError("GeoServer این پایگاه داده قبلاً درخواست شده است.")
    inst.status = GeoServerInstance.Status.REQUESTED
    inst.save(update_fields=["status"])
    Job.objects.create(kind=Job.Kind.GEOSERVER, database=db, user=user, status=Job.Status.QUEUED)
    return inst


def _geoserver_role(db: UserDatabase) -> tuple[str, str]:
    """کاربر فقط‌خواندنی جداگانه برای GeoServer (رمز اصلی مشتری در GeoServer نمی‌نشیند)."""
    from databases import team
    from databases.crypto import generate_password
    from databases.services import limits_for, provisioner_for

    name = team.role_name_for(db, geoserver.ROLE_SUFFIX)
    password = generate_password()
    if DbRole.objects.filter(name=name).exists():
        provisioner_for(db.server).set_password(name, password)
    else:
        DbRole.objects.create(database=db, name=name, access=DbRole.Access.READ, note="GeoServer اختصاصی (خودکار)")
        provisioner_for(db.server).create_extra_role(db.db_name, db.role_name, name, password, write=False,
                                                     limits=limits_for(db.plan))
    return name, password


def provision(job: Job) -> str:
    inst = GeoServerInstance.objects.get(database=job.database)
    if not inst.url:
        if not geoserver.coolify_enabled():
            from core.alerts import notify_admins

            inst.message = "در انتظار ساخت دستی توسط مدیر."
            inst.save(update_fields=["message"])
            notify_admins("GeoServer اختصاصی", f"درخواست GeoServer برای {job.database.db_name}. "
                                                "در پنل مدیریت آدرس و رمز را وارد و «پیکربندی» را بزنید.")
            return inst.message
        inst.status = GeoServerInstance.Status.PROVISIONING
        inst.save(update_fields=["status"])
        geoserver.create_container(inst)
        inst.save()
    try:
        inst.version = geoserver.wait_until_up(inst)
        name, password = _geoserver_role(inst.database)
        res = geoserver.bootstrap(inst, name, password)
    except geoserver.GeoServerError as exc:
        inst.status = GeoServerInstance.Status.FAILED
        inst.message = str(exc)[:1000]
        inst.save(update_fields=["status", "message"])
        raise EnterpriseError(str(exc)) from exc
    inst.status = GeoServerInstance.Status.ACTIVE
    inst.message = (f"GeoServer {inst.version} آماده است؛ workspace «{res['workspace']}» با "
                    f"{len(res['published'])} لایه." + (f" ناموفق: {', '.join(res['failed'])}" if res["failed"] else ""))
    inst.save(update_fields=["status", "message", "version"])
    return inst.message


# ---------------------------------------------------------------------- رستر
def raster_used(db: UserDatabase) -> int:
    return db.rasters.aggregate(s=Sum("size_bytes"))["s"] or 0


def _run(cmd: list[str], timeout: int = 3600) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              env={"GDAL_HTTP_PROXY": "127.0.0.1:9", "PATH": "/usr/bin:/usr/local/bin:/bin"})
    except subprocess.TimeoutExpired as exc:
        raise EnterpriseError("پردازش رستر بیش از حد طول کشید.") from exc
    if proc.returncode != 0:
        raise EnterpriseError(f"{Path(cmd[0]).name}: {proc.stderr.strip()[-400:]}")
    return proc.stdout


def raster_upload_path(raster: Raster) -> Path:
    return Path(settings.RASTER_ROOT) / "incoming" / f"{raster.slug}.upload"


def request_raster(db: UserDatabase, user, upload, title: str) -> Raster:
    cap = db.plan.raster_mb * 1024 * 1024
    if not cap:
        raise EnterpriseError("سرویس رستر در پلن سازمانی فعال است.")
    if db.status != UserDatabase.Status.ACTIVE:
        raise EnterpriseError("پایگاه داده فعال نیست.")
    if Path(upload.name).suffix.lower() not in RASTER_EXT:
        raise EnterpriseError("فقط GeoTIFF (.tif) پذیرفته می‌شود.")
    if upload.size > settings.RASTER_MAX_MB * 1024 * 1024:
        raise EnterpriseError(f"حداکثر حجم هر فایل {settings.RASTER_MAX_MB} مگابایت است.")
    head = next(iter(upload.chunks(16)), b"")[:4]
    upload.seek(0)
    if head not in TIFF_MAGIC:
        raise EnterpriseError("محتوای فایل GeoTIFF نیست.")
    if raster_used(db) + upload.size > cap:
        raise EnterpriseError("فضای رستر پلن پر می‌شود؛ رسترهای قدیمی را حذف کنید.")
    r = Raster.objects.create(database=db, title=(title or Path(upload.name).stem)[:120], original_name=upload.name[:255],
                              created_by=user)
    dest = raster_upload_path(r)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        for chunk in upload.chunks():
            f.write(chunk)
    Job.objects.create(kind=Job.Kind.RASTER, database=db, user=user, status=Job.Status.QUEUED, params={"raster": r.pk})
    return r


def process_raster(job: Job) -> str:
    r = Raster.objects.get(pk=job.params["raster"])
    src = raster_upload_path(r)
    out = r.path
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        info = json.loads(_run(["gdalinfo", "-json", str(src)], 300))
        if not info.get("coordinateSystem", {}).get("wkt"):
            raise EnterpriseError("فایل سیستم مختصات ندارد (prj یا اطلاعات GeoTIFF).")
        tmp = out.with_suffix(".part.tif")
        _run(["gdal_translate", "-of", "COG", "-co", "COMPRESS=DEFLATE", "-co", "OVERVIEWS=AUTO",
              "-co", "BLOCKSIZE=512", "-co", "NUM_THREADS=2", str(src), str(tmp)])
        tmp.replace(out)
        info = json.loads(_run(["gdalinfo", "-json", "-stats", str(out)], 900))
        out.with_suffix(".tif.aux.xml").unlink(missing_ok=True)
    except Exception as exc:
        r.status, r.message = Raster.Status.FAILED, str(exc)[:1000]
        r.save(update_fields=["status", "message"])
        raise
    finally:
        src.unlink(missing_ok=True)
    bands = info.get("bands", [])
    r.width, r.height = info["size"]
    r.bands = len(bands)
    r.dtype = bands[0].get("type", "") if bands else ""
    r.crs = (info.get("stac", {}).get("proj:epsg") and f"EPSG:{info['stac']['proj:epsg']}") or "custom"
    wgs = info.get("wgs84Extent", {}).get("coordinates", [[]])[0]
    if wgs:
        xs, ys = [p[0] for p in wgs], [p[1] for p in wgs]
        r.bounds = [min(xs), min(ys), max(xs), max(ys)]
    r.stats = [[b.get("minimum"), b.get("maximum")] for b in bands]
    r.rgb = r.bands >= 3 and r.dtype == "Byte"
    r.size_bytes = out.stat().st_size
    r.status, r.message = Raster.Status.READY, ""
    r.save()
    return f"رستر «{r.title}» آماده شد ({r.width}×{r.height}، {r.bands} باند)."


def delete_raster(r: Raster) -> None:
    r.path.unlink(missing_ok=True)
    raster_upload_path(r).unlink(missing_ok=True)
    r.delete()


# ---------------------------------------------------------------------- کپی پایگاه داده
def request_clone(db: UserDatabase, user, backup: Job | None, label: str) -> tuple[UserDatabase, str]:
    """پایگاه داده آزمایشی از آخرین بکاپ (یا بکاپ انتخابی): پایگاه داده جدید ساخته و داده در worker ریخته می‌شود."""
    from databases import services as db_services
    from databases.crypto import generate_password

    if not db.plan.clone_enabled:
        raise EnterpriseError("کپی پایگاه داده در پلن سازمانی فعال است.")
    backup = backup or db.jobs.filter(kind=Job.Kind.BACKUP, status=Job.Status.DONE).first()
    if backup is None or not backup.downloadable:
        raise EnterpriseError("بکاپ سالمی برای کپی نیست؛ اول یک بکاپ بگیرید.")
    live_clones = UserDatabase.objects.filter(
        pk__in=Job.objects.filter(kind=Job.Kind.CLONE, params__from=db.pk).values("database_id"),
        status__in=UserDatabase.LIVE_STATUSES).count()
    if live_clones >= MAX_CLONES:
        raise EnterpriseError(f"حداکثر {MAX_CLONES} کپی فعال؛ یک کپی قدیمی را حذف کنید.")
    password = generate_password()
    try:
        # کپی جزو سقف تعداد پایگاه داده کاربر نیست، ولی هم‌زمان با اصلی منقضی می‌شود
        clone = db_services.create_database(user, label, password, [], plan=db.plan, ignore_limit=True)
    except db_services.ServiceError as exc:
        raise EnterpriseError(str(exc)) from exc
    clone.expires_at = db.expires_at
    clone.save(update_fields=["expires_at"])
    Job.objects.create(kind=Job.Kind.CLONE, database=clone, user=user, source=backup, status=Job.Status.QUEUED,
                       params={"from": db.pk})
    return clone, password


def do_clone(job: Job) -> str:
    from databases.provisioner import Provisioner
    from jobs.services import restore_into

    clone, src = job.database, job.source
    if src is None or not src.path or not src.path.exists():
        raise EnterpriseError("فایل بکاپ پیدا نشد.")
    restore_into(clone.server, clone.db_name, src.path)
    info = Provisioner.for_server(clone.server).finish_restore(clone.db_name, clone.role_name)
    when = timezone.localtime(src.created_at).strftime("%Y-%m-%d %H:%M")
    return f"کپی از بکاپ {when} ساخته شد ({info['tables']} جدول)."


# ---------------------------------------------------------------------- بکاپ ساعتی
def schedule_snapshots(now=None) -> int:
    now = now or timezone.now()
    n = 0
    for db in UserDatabase.objects.filter(status__in=UserDatabase.LIVE_STATUSES, plan__snapshot_hours__gt=0
                                          ).select_related("plan"):
        since = now - timedelta(hours=db.plan.snapshot_hours) + timedelta(minutes=2)
        if Job.objects.filter(database=db, kind=Job.Kind.BACKUP, params__snapshot=True, created_at__gte=since).exists():
            continue
        if Job.objects.filter(database=db, kind__in=[Job.Kind.BACKUP, Job.Kind.RESTORE],
                              status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).exists():
            continue
        Job.objects.create(kind=Job.Kind.BACKUP, trigger=Job.Trigger.SYSTEM, database=db, params={"snapshot": True})
        n += 1
    return n


def cleanup_rasters_dir() -> None:
    root = Path(settings.RASTER_ROOT) / "incoming"
    if root.exists():
        cutoff = timezone.now().timestamp() - 86400
        for f in root.iterdir():
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
