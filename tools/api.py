"""نقطه ورود مشترک اجرای ابزار از رابط‌های کاربری."""
from django.db import transaction

from analysis.models import ToolRun
from databases.models import UserDatabase
from jobs.models import Job
from kernel import tenantdb

from . import engine, sdk


@transaction.atomic
def enqueue(db, user, key, values):
    # یک صف مشترک برای تحلیل و ابزار؛ قفل روی رکورد پنل نه داده مشتری.
    db = UserDatabase.objects.select_for_update().get(pk=db.pk)
    if db.status != db.Status.ACTIVE:
        raise sdk.ToolError("پایگاه داده فقط‌خواندنی یا غیرفعال است.")
    if Job.objects.filter(database=db, kind__in=[Job.Kind.ASK, Job.Kind.TOOL],
                          status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).exists():
        raise sdk.ToolError("یک تحلیل در حال اجراست.")
    info = sdk.get(key)
    if info is None:
        raise sdk.ToolError("ابزار پیدا نشد.")
    if info.needs_routing and not any(t.schema == "routing" and t.name == "ways"
                                     for t in tenantdb.catalog(db).tables()):
        raise sdk.ToolError("به شبکه معابر نیاز دارد.")
    vals = {k: values.get(k, "").strip() for k in engine.public_params(key) if values.get(k)}
    out = engine.validate(db, key, vals)
    summary = engine.summarize(db, key, vals)
    job = Job.objects.create(kind=Job.Kind.TOOL, database=db, user=user, status=Job.Status.QUEUED)
    ToolRun.objects.create(database=db, user=user, tool=key, params=vals, summary=summary, output_table=out, job=job)
    return job
