"""کارهای worker برای نقشه پایه و داده OSM ایران."""
from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from jobs.models import Job

from . import basemap, osm


def do_basemap(job: Job) -> None:
    res = basemap.build()
    job.size_bytes = res["size"]
    job.message = f"نقشه پایه از {res['source']} ساخته شد."


def do_osm_refresh(job: Job) -> None:
    if job.params.get("download", True):
        osm.download_source()
    else:
        osm.refresh_areas()
    from .models import Area

    job.message = f"داده OSM ایران به‌روز شد؛ {Area.objects.count()} ناحیه."


def do_osm_import(job: Job) -> None:
    from .ready import run_import

    job.message = run_import(job)


def _due(kind: str, days: int, now: datetime) -> bool:
    if days <= 0:
        return False
    recent = Job.objects.filter(kind=kind, created_at__gte=now - timedelta(days=days))
    return not recent.exclude(status=Job.Status.FAILED).exists() and not recent.filter(
        status=Job.Status.FAILED, created_at__gte=now - timedelta(days=1)).exists()


def schedule(now: datetime | None = None) -> int:
    """نقشه پایه هر BASEMAP_REFRESH_DAYS و داده OSM هر OSM_REFRESH_DAYS روز، ساعت ۴ بامداد تهران."""
    now = now or timezone.now()
    if timezone.localtime(now).hour != 4:
        return 0
    n = 0
    for kind, days in ((Job.Kind.BASEMAP, settings.BASEMAP_REFRESH_DAYS),
                       (Job.Kind.OSM_REFRESH, settings.OSM_REFRESH_DAYS)):
        if _due(kind, days, now) and not Job.objects.filter(kind=kind, status__in=[Job.Status.QUEUED,
                                                                                    Job.Status.RUNNING]).exists():
            Job.objects.create(kind=kind, trigger=Job.Trigger.AUTO, status=Job.Status.QUEUED)
            n += 1
    return n
