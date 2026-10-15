"""پلن کلاس: صفحه معرفی و درخواست قرارداد، پنل استاد، ثبت‌نام دانشجو با کد."""
import csv

from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.decorators import site_user_required
from core.models import SiteSettings

from . import services
from .models import Classroom, Contract, ContractRequest, Enrollment

SESSION_PW = "class_join_pw_{}"


@require_http_methods(["GET", "POST"])
def landing(request):
    sent = False
    errors = {}
    data = {}
    if request.method == "POST":
        from django.core.exceptions import ValidationError

        from accounts.models import normalize_mobile

        data = {k: (request.POST.get(k) or "").strip() for k in
                ("institution", "name", "phone", "email", "students", "term", "course", "message")}
        if request.POST.get("website"):  # تله ربات
            return redirect("classroom:landing")
        for k in ("institution", "name", "phone"):
            if not data[k]:
                errors[k] = "لازم است."
        try:
            data["phone"] = normalize_mobile(data["phone"]) if data["phone"] else ""
        except ValidationError:
            errors["phone"] = "شماره موبایل معتبر نیست."
        try:
            students = max(1, min(5000, int(data["students"].translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
                                            or 30)))
        except ValueError:
            errors["students"] = "عدد بنویسید."
            students = 30
        if not errors:
            req = ContractRequest.objects.create(
                institution=data["institution"][:200], name=data["name"][:150], phone=data["phone"],
                email=data["email"][:254], students=students, term=data["term"][:100], course=data["course"][:150],
                message=data["message"][:3000])
            try:
                from core.alerts import notify_admins

                notify_admins("درخواست پلن کلاس", f"{req.institution} — {req.name} ({req.phone})، {req.students} دانشجو")
            except Exception:  # noqa: BLE001  ارسال هشدار نباید ثبت را خراب کند
                pass
            sent = True
            data = {}
    conf = SiteSettings.get()
    return render(request, "classroom/landing.html", {"sent": sent, "errors": errors, "data": data,
                                                      "price": conf.class_price_per_student})


@site_user_required
@require_http_methods(["GET", "POST"])
def teach(request):
    contracts = list(services.teacher_contracts(request.user))
    classes = Classroom.objects.filter(teacher=request.user).select_related("contract")
    if not contracts and not classes.exists():
        return render(request, "classroom/not_teacher.html")
    error = None
    if request.method == "POST":
        from iranmap.models import Area

        contract = get_object_or_404(Contract, pk=request.POST.get("contract") or 0)
        area = Area.objects.filter(pk=request.POST.get("area") or 0).first()
        try:
            cap = int(request.POST.get("capacity") or 0)
            c = services.create_class(request.user, contract, request.POST.get("title", ""),
                                      request.POST.get("template", "sample"), cap, area)
        except (services.ClassError, ValueError) as exc:
            error = str(exc) if isinstance(exc, services.ClassError) else "ظرفیت را عدد بنویسید."
        else:
            messages.success(request, f"کلاس «{c.title}» ساخته شد؛ لینک ثبت‌نام را برای دانشجوها بفرستید.")
            return redirect("classroom:detail", pk=c.pk)
    from iranmap.models import Area

    return render(request, "classroom/teach.html", {
        "contracts": contracts, "classes": classes, "error": error, "templates": Classroom.Template.choices,
        "cities": Area.objects.filter(level__in=["city", "county"]).order_by("name")[:500],
    })


def _my_class(request, pk) -> Classroom:
    return get_object_or_404(Classroom.objects.select_related("contract"), pk=pk, teacher=request.user)


@site_user_required
@require_http_methods(["GET", "POST"])
def detail(request, pk):
    c = _my_class(request, pk)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "toggle" and c.status == Classroom.Status.ACTIVE:
            c.is_open = not c.is_open
            c.save(update_fields=["is_open"])
            messages.success(request, "ثبت‌نام باز شد." if c.is_open else "ثبت‌نام بسته شد.")
        elif action == "archive" and c.status == Classroom.Status.ACTIVE:
            n = services.archive(c)
            messages.success(request, f"کلاس بایگانی شد؛ از {n} پایگاه داده بکاپ گرفته می‌شود. پایگاه‌ها تا پایان "
                                      "ترم قابل استفاده می‌مانند.")
        return redirect("classroom:detail", pk=c.pk)
    rows = c.enrollments.select_related("database", "archive", "student")
    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="class-{c.pk}.csv"'
        resp.write("﻿")
        w = csv.writer(resp)
        w.writerow(["نام", "شماره دانشجویی", "موبایل", "پایگاه داده", "نام کاربری", "حجم (بایت)", "ثبت‌نام"])
        for e in rows:
            db = e.database
            w.writerow([e.full_name, e.student_no, e.student.phone, db.db_name if db else "", db.role_name if db else "",
                        db.size_bytes if db else 0, e.joined_at.date().isoformat()])
        return resp
    return render(request, "classroom/detail.html", {
        "c": c, "rows": rows, "join_url": request.build_absolute_uri(f"/class/join/{c.code}/")})


@site_user_required
def archive_download(request, pk, enrollment_id):
    c = _my_class(request, pk)
    e = get_object_or_404(Enrollment, pk=enrollment_id, classroom=c)
    job = e.archive
    if job is None or not job.downloadable or not job.path.exists():
        raise Http404
    name = f"{c.pk}-{e.student_no or e.pk}-{job.path.name}"
    return FileResponse(job.path.open("rb"), as_attachment=True, filename=name, content_type="application/octet-stream")


@site_user_required
@require_http_methods(["GET", "POST"])
def join(request, code):
    c = Classroom.objects.select_related("contract", "teacher").filter(code=code.upper()).first()
    if c is None:
        raise Http404
    mine = Enrollment.objects.filter(classroom=c, student=request.user).select_related("database").first()
    error = None
    if request.method == "POST" and mine is None:
        try:
            mine, pw = services.join(c, request.user, request.POST.get("full_name", ""),
                                     request.POST.get("student_no", ""))
        except services.ClassError as exc:
            error = str(exc)
        else:
            request.session[SESSION_PW.format(mine.pk)] = pw
            return redirect("classroom:join", code=c.code)
    pw = request.session.pop(SESSION_PW.format(mine.pk), None) if mine else None
    return render(request, "classroom/join.html", {"c": c, "mine": mine, "password": pw, "error": error})
