"""نماهای «بکاپ و بازگردانی» یک پایگاه داده."""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import site_user_required
from databases.forms import DeleteConfirmForm
from kernel import workspace


# ---------------------------------------------------------------------- بکاپ و بازگردانی
@site_user_required
def backups(request, pk):
    from jobs.models import Job

    db = workspace.get(request, pk)
    jobs = list(db.jobs.filter(kind__in=[Job.Kind.BACKUP, Job.Kind.RESTORE]).select_related("source")[:40])
    return render(request, "databases/backups.html", {
        "db": db, "jobs": jobs, "busy": any(j.active for j in jobs),
        "available": [j for j in jobs if j.downloadable],
        "restore_form": DeleteConfirmForm(expected=db.label),
        "keep_days": db.plan.backup_retention_days,
    })


@site_user_required
@require_POST
def backup_new(request, pk):
    from jobs import services as jobs

    db = workspace.get(request, pk)
    try:
        jobs.request_backup(db, request.user)
    except jobs.JobError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "بکاپ در صف قرار گرفت. معمولاً چند دقیقه طول می‌کشد؛ این صفحه را تازه کنید.")
    return redirect("databases:backups", pk=db.pk)


@site_user_required
def backup_download(request, pk, job_id):
    from django.http import FileResponse

    db = workspace.get(request, pk)
    from jobs import offsite

    job = get_object_or_404(db.jobs, pk=job_id)
    if not job.downloadable:
        raise Http404
    path = offsite.ensure_local(job)  # اگر فایل محلی گم شده باشد، از نسخه‌ی ابری برمی‌گردد
    if path is None:
        raise Http404
    return FileResponse(path.open("rb"), as_attachment=True, filename=path.name,
                        content_type="application/octet-stream")


@site_user_required
@require_POST
def backup_restore(request, pk, job_id):
    from jobs import services as jobs

    db = workspace.get(request, pk)
    backup = get_object_or_404(db.jobs, pk=job_id)
    form = DeleteConfirmForm(request.POST, expected=db.label)
    if not form.is_valid():
        messages.error(request, "نام وارد‌شده مطابقت نداشت؛ بازگردانی انجام نشد.")
        return redirect("databases:backups", pk=db.pk)
    try:
        jobs.request_restore(db, backup, request.user)
    except jobs.JobError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "بازگردانی در صف قرار گرفت. قبل از آن یک بکاپ ایمنی از وضع فعلی گرفته می‌شود.")
    return redirect("databases:backups", pk=db.pk)
