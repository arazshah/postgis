"""درخواست و اجرای «داده آماده ایران» برای پایگاه داده کاربر."""
from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from databases.models import UserDatabase
from jobs.models import Job

from . import osm
from .models import Area

DAILY_LIMIT = 5
ROUTING_MAX_DEG2 = 0.6  # حدود یک شهر بزرگ یا شهرستان؛ استان کامل برای گراف مسیریابی سنگین است


class ReadyError(Exception):
    pass


def routing_allowed(area: Area) -> bool:
    return area.level != "province" and area.area_deg2 <= ROUTING_MAX_DEG2


def pgrouting_available(db: UserDatabase) -> bool:
    from databases.provisioner import Provisioner

    try:
        return Provisioner.for_server(db.server).extension_available("pgrouting")
    except Exception:  # noqa: BLE001  سرور در دسترس نیست
        return False


def request_import(db: UserDatabase, user, area: Area, datasets: list[str], routing: bool) -> Job:
    if db.status != UserDatabase.Status.ACTIVE:
        raise ReadyError("پایگاه داده فقط‌خواندنی یا غیرفعال است؛ ورود داده ممکن نیست.")
    if not osm.source_file().exists():
        raise ReadyError("داده OSM ایران هنوز روی سرور آماده نیست؛ کمی بعد دوباره امتحان کنید.")
    datasets = [d for d in datasets if d in osm.DATASET_MAP]
    if not datasets and not routing:
        raise ReadyError("دست‌کم یک دسته داده یا شبکه مسیریابی را انتخاب کنید.")
    if routing and not routing_allowed(area):
        raise ReadyError("شبکه مسیریابی فقط برای شهر یا شهرستان ساخته می‌شود، نه یک استان کامل.")
    if routing and not pgrouting_available(db):
        raise ReadyError("افزونه pgRouting روی سرور این پایگاه داده نصب نیست؛ فقط داده‌ها را انتخاب کنید یا تیکت بزنید.")
    jobs = Job.objects.filter(database=db, kind=Job.Kind.OSM_IMPORT)
    if jobs.filter(status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).exists():
        raise ReadyError("یک درخواست داده آماده در حال انجام است؛ صبر کنید تمام شود.")
    if jobs.filter(created_at__gte=timezone.now() - timedelta(days=1)).count() >= DAILY_LIMIT:
        raise ReadyError(f"حداکثر {DAILY_LIMIT} درخواست داده آماده در روز.")
    return Job.objects.create(kind=Job.Kind.OSM_IMPORT, database=db, user=user, status=Job.Status.QUEUED,
                              params={"area": area.pk, "area_label": area.label, "datasets": datasets,
                                      "routing": bool(routing)})


def run_import(job: Job) -> str:
    from databases.provisioner import Provisioner

    db = job.database
    area = Area.objects.filter(pk=job.params.get("area")).first()
    if area is None:
        raise osm.OsmError("ناحیه انتخاب‌شده دیگر در فهرست نیست؛ دوباره درخواست دهید.")
    done = []
    keys = job.params.get("datasets", [])
    routing = bool(job.params.get("routing"))
    steps = len(keys) + (1 if routing else 0)
    # ۵٪ برای برش محدوده، ۹۰٪ بین مراحل ورود، بقیه برای نهایی‌سازی
    job.set_progress(3, "برش محدوده از داده ایران")
    root = Path(settings.OSM_ROOT) / "work"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as d:
        pbf = osm.extract(area, Path(d) / "area.osm.pbf")
        for i, key in enumerate(keys):
            ds = osm.DATASET_MAP[key]
            job.set_progress(8 + 85 * i // steps, f"ورود {ds.title}")
            n = osm.import_dataset(db, pbf, ds)
            done.append(f"osm_{key} ({n:,} عارضه)")
        if routing:
            job.set_progress(8 + 85 * len(keys) // steps, "ساخت شبکه مسیریابی")
            n = osm.import_routing(db, pbf)
            done.append(f"routing.ways ({n:,} یال)")
    # اطمینان: همه اشیای ساخته‌شده مال نقش خود کاربر باشند
    job.set_progress(96, "تنظیم دسترسی جدول‌ها")
    Provisioner.for_server(db.server).reassign_browser_objects(db.db_name, db.role_name)
    return f"{area.label}: " + "، ".join(done)
