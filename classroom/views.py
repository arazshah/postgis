"""پلن کلاس: صفحه معرفی و درخواست قرارداد، پنل استاد، ثبت‌نام دانشجو با کد."""
import csv

from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from accounts.decorators import site_user_required
from core.models import SiteSettings
from databases.explorer import ExplorerError

from . import services
from .models import ClassMap, Classroom, Contract, ContractRequest, Enrollment, Submission

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
        elif action == "share_map" and c.status == Classroom.Status.ACTIVE:
            webmap = _teacher_maps(request.user).filter(pk=request.POST.get("map") or 0).first()
            if webmap is None:
                messages.error(request, "نقشه را انتخاب کنید.")
            else:
                cm, created = ClassMap.objects.get_or_create(classroom=c, webmap=webmap)
                cm.note = (request.POST.get("note") or "").strip()[:2000]
                cm.save(update_fields=["note"])
                messages.success(request, f"نقشه «{webmap.title}» با کلاس به اشتراک گذاشته شد." if created
                                 else "توضیح نقشه به‌روز شد.")
        elif action == "unshare_map":
            ClassMap.objects.filter(classroom=c, pk=request.POST.get("share") or 0).delete()
            messages.success(request, "نقشه از کلاس برداشته شد.")
        elif action in ("assignment_save", "assignment_toggle", "assignment_delete"):
            _assignment_action(request, c, action)
        elif action == "archive" and c.status == Classroom.Status.ACTIVE:
            n = services.archive(c)
            messages.success(request, f"کلاس بایگانی شد؛ از {n} پایگاه داده بکاپ گرفته می‌شود. پایگاه‌ها تا پایان "
                                      "ترم قابل استفاده می‌مانند.")
        return redirect("classroom:detail", pk=c.pk)
    rows = c.enrollments.select_related("database", "archive", "student").prefetch_related("submissions")
    assignments = list(c.assignments.select_related("class_map__webmap").prefetch_related("submissions"))
    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="class-{c.pk}.csv"'
        resp.write("﻿")
        w = csv.writer(resp)
        w.writerow(["نام", "شماره دانشجویی", "موبایل", "پایگاه داده", "نام کاربری", "حجم (بایت)", "ثبت‌نام"]
                   + [f"{a.title} (از {a.max_score})" for a in assignments])
        for e in rows:
            db = e.database
            marks = {s.assignment_id: s for s in e.submissions.all()}
            w.writerow([e.full_name, e.student_no, e.student.phone, db.db_name if db else "", db.role_name if db else "",
                        db.size_bytes if db else 0, e.joined_at.date().isoformat()]
                       + [_mark(marks.get(a.pk)) for a in assignments])
        return resp
    shared = c.maps.select_related("webmap")
    total = len(rows)
    for a in assignments:
        a.stats = services.summary(a, total)
    return render(request, "classroom/detail.html", {
        "c": c, "rows": rows, "join_url": request.build_absolute_uri(f"/class/join/{c.code}/"),
        "assignments": assignments, "shared": shared,
        "my_maps": _teacher_maps(request.user).exclude(pk__in=[x.webmap_id for x in shared])})


def _mark(sub) -> str:
    """نمره یا وضعیت یک تحویل برای CSV."""
    if sub is None:
        return "تحویل نشده"
    if sub.status == Submission.Status.GRADED:
        return f"{sub.score.normalize():f}"
    return sub.get_status_display()


def _assignment_action(request, c: Classroom, action: str) -> None:
    """ساخت/ویرایش، نمایش یا پنهان‌کردن و حذف تمرین از صفحه کلاس."""
    pk = request.POST.get("assignment") or 0
    a = c.assignments.filter(pk=pk).first() if pk else None
    if action == "assignment_save":
        if pk and a is None:
            raise Http404
        try:
            saved = services.save_assignment(c, request.POST, a)
        except services.ClassError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"تمرین «{saved.title}» " + ("به‌روز شد." if a else "ساخته شد."))
        return
    if a is None:
        raise Http404
    if action == "assignment_toggle":
        a.is_published = not a.is_published
        a.save(update_fields=["is_published"])
        messages.success(request, "تمرین برای دانشجوها دیده می‌شود." if a.is_published else "تمرین پنهان شد.")
    else:
        a.delete()
        messages.success(request, f"تمرین «{a.title}» با همه‌ی تحویل‌هایش حذف شد.")


@site_user_required
def assignment_review(request, pk, aid):
    """فهرست تحویل‌های یک تمرین برای استاد: چه کسی تحویل داده، چه کسی نه، نمره‌ها."""
    c = _my_class(request, pk)
    a = get_object_or_404(c.assignments.select_related("class_map__webmap"), pk=aid)
    rows = services.roster(a)
    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="class-{c.pk}-assignment-{a.pk}.csv"'
        resp.write("﻿")
        w = csv.writer(resp)
        w.writerow(["نام", "شماره دانشجویی", "وضعیت", "با تأخیر", "زمان تحویل", f"نمره (از {a.max_score})",
                    "بازخورد"])
        for e, sub in rows:
            w.writerow([e.full_name, e.student_no, sub.get_status_display() if sub else "تحویل نشده",
                        "بله" if sub and sub.is_late else "",
                        timezone.localtime(sub.submitted_at).strftime("%Y-%m-%d %H:%M") if sub else "",
                        f"{sub.score.normalize():f}" if sub and sub.score is not None else "",
                        sub.feedback if sub else ""])
        return resp
    return render(request, "classroom/assignment_review.html", {
        "c": c, "a": a, "rows": rows, "stats": services.summary(a, len(rows)),
        "need": next((e.pk for e, sub in rows if sub and sub.status == Submission.Status.SUBMITTED), None)})


@site_user_required
@require_http_methods(["GET", "POST"])
def assignment_grade(request, pk, aid, eid):
    """بررسی تحویل یک دانشجو: دیدن پاسخ و نقشه، نمره‌دادن یا برگرداندن برای اصلاح."""
    c = _my_class(request, pk)
    a = get_object_or_404(c.assignments, pk=aid)
    e = get_object_or_404(c.enrollments.select_related("database", "student"), pk=eid)
    sub = Submission.objects.filter(assignment=a, enrollment=e).select_related("webmap").first()
    rows = services.roster(a)
    if request.method == "POST" and sub is not None:
        try:
            services.grade(sub, request.POST.get("do", "").removesuffix("_next"), request.POST.get("score", ""),
                           request.POST.get("feedback", ""))
        except services.ClassError as exc:
            messages.error(request, str(exc))
            return redirect("classroom:assignment_grade", pk=c.pk, aid=a.pk, eid=e.pk)
        messages.success(request, f"نمره‌ی {e.full_name} ثبت شد." if sub.status == Submission.Status.GRADED
                         else f"تمرین {e.full_name} برای اصلاح برگشت.")
        nxt = next((x.pk for x, s in rows if s and s.status == Submission.Status.SUBMITTED and x.pk != e.pk), None)
        if nxt and request.POST.get("do") == "grade_next":
            return redirect("classroom:assignment_grade", pk=c.pk, aid=a.pk, eid=nxt)
        return redirect("classroom:assignment_review", pk=c.pk, aid=a.pk)
    ids = [x.pk for x, _ in rows]
    i = ids.index(e.pk)
    nxt = next((x.pk for x, s in rows if s and s.status == Submission.Status.SUBMITTED and x.pk != e.pk), None)
    return render(request, "classroom/assignment_grade.html", {
        "c": c, "a": a, "e": e, "sub": sub, "next_waiting": nxt,
        "prev_id": ids[i - 1] if i else None, "next_id": ids[i + 1] if i + 1 < len(ids) else None})


def _teacher_maps(user):
    """نقشه‌های پایگاه داده‌های خود استاد (نه پایگاه داده دانشجوها)."""
    from databases.models import UserDatabase
    from maps.models import WebMap

    return (WebMap.objects.filter(database__owner=user, database__enrollment__isnull=True)
            .exclude(database__status=UserDatabase.Status.DELETED).select_related("database"))


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
    is_teacher = c.teacher_id == request.user.pk
    shared = c.maps.select_related("webmap") if mine or is_teacher else []
    todo = []
    if mine or is_teacher:
        marks = {s.assignment_id: s for s in mine.submissions.all()} if mine else {}
        todo = list(c.assignments.all() if is_teacher else c.assignments.filter(is_published=True))
        for a in todo:
            a.mine = marks.get(a.pk)
    return render(request, "classroom/join.html", {"c": c, "mine": mine, "password": pw, "error": error,
                                                   "shared": shared, "assignments": todo, "is_teacher": is_teacher})


@site_user_required
@require_http_methods(["GET", "POST"])
def enter(request):
    """ورود با کد: دانشجو کد را می‌نویسد؛ کلاس‌هایی که در آن‌ها ثبت‌نام کرده هم این‌جا فهرست است."""
    error = None
    code = ""
    if request.method == "POST":
        code = (request.POST.get("code") or "").strip().upper().replace(" ", "")
        if Classroom.objects.filter(code=code).exists():
            return redirect("classroom:join", code=code)
        error = "کلاسی با این کد پیدا نشد؛ کد را از استاد دوباره بگیرید."
    mine = (Enrollment.objects.filter(student=request.user).select_related("classroom__contract", "database")
            .order_by("-joined_at"))
    for e in mine:
        e.open_count = e.classroom.assignments.filter(is_published=True).exclude(submissions__enrollment=e).count()
    return render(request, "classroom/enter.html", {"error": error, "code": code, "mine": mine})


@site_user_required
@require_http_methods(["GET", "POST"])
def assignment_page(request, code, aid):
    """صفحه‌ی تمرین برای دانشجو: صورت مسئله، تحویل و نمره؛ استاد کلاس پیش‌نمایش را می‌بیند."""
    c = get_object_or_404(Classroom.objects.select_related("contract", "teacher"), code=code.upper())
    mine = Enrollment.objects.filter(classroom=c, student=request.user).select_related("database").first()
    preview = mine is None and c.teacher_id == request.user.pk
    if mine is None and not preview:
        raise Http404
    a = get_object_or_404(c.assignments.select_related("class_map__webmap"), pk=aid,
                          **({} if preview else {"is_published": True}))
    sub = Submission.objects.filter(assignment=a, enrollment=mine).select_related("webmap").first() if mine else None
    if request.method == "POST" and mine is not None:
        try:
            services.submit(a, mine, request.POST.get("note", ""), request.POST.get("webmap"))
        except services.ClassError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "تمرین شما تحویل شد." + (" (بعد از مهلت)" if a.is_overdue else ""))
        return redirect("classroom:assignment", code=c.code, aid=a.pk)
    from maps.models import WebMap

    my_maps = (WebMap.objects.filter(database=mine.database) if mine and mine.database_id else WebMap.objects.none())
    locked = bool(sub and sub.status == Submission.Status.GRADED) or c.status != Classroom.Status.ACTIVE
    return render(request, "classroom/assignment.html", {
        "c": c, "a": a, "mine": mine, "sub": sub, "preview": preview, "my_maps": my_maps, "locked": locked})


@site_user_required
@require_POST
def copy_map(request, code, share_id):
    """کپی نقشه کلاس در پایگاه داده کلاسی دانشجو؛ لایه‌ها به جدول‌های هم‌نام خود دانشجو وصل می‌شوند."""
    from maps import services as map_services

    c = get_object_or_404(Classroom, code=code.upper())
    cm = get_object_or_404(ClassMap.objects.select_related("webmap"), pk=share_id, classroom=c)
    mine = Enrollment.objects.filter(classroom=c, student=request.user).select_related("database__plan").first()
    if mine is None or mine.database is None or not mine.database.is_live:
        raise Http404
    try:
        copy, skipped = map_services.copy_to(cm.webmap, mine.database, request.user)
    except (map_services.MapError, ExplorerError) as exc:
        messages.error(request, str(exc))
        return redirect("classroom:join", code=c.code)
    msg = f"نقشه «{copy.title}» در پایگاه داده شما ساخته شد."
    if skipped:
        msg += " این موارد جدول یا ستون‌های هم‌نام در پایگاه داده شما نداشتند و کپی نشدند: " + "، ".join(skipped)
    messages.success(request, msg)
    return redirect("maps:composer", pk=mine.database.pk, map_id=copy.pk)
