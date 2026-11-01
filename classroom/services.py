"""ساخت کلاس، ثبت‌نام دانشجو (پایگاه داده جدا برای هر نفر) و بایگانی پایان ترم."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from databases import services as db_services
from databases.crypto import generate_password
from databases.models import Member, Plan, UserDatabase
from jobs.models import Job

from .models import Assignment, ClassMap, Classroom, Contract, Enrollment, Submission

log = logging.getLogger(__name__)
SAMPLE_DIR = Path(__file__).parent / "sample"
SAMPLE_LAYERS = ("schools", "metro_stations", "parks")
ARCHIVE_KEEP_DAYS = 180


class ClassError(Exception):
    pass


def class_plan(quota_mb: int) -> Plan:
    """پلن مخفی کلاس برای هر حجم؛ تمدید نمی‌شود و تا پایان ترم اعتبار دارد."""
    plan, _ = Plan.objects.get_or_create(slug=f"class-{quota_mb}", defaults={
        "name": f"کلاس ({quota_mb} مگابایت)", "quota_mb": quota_mb, "max_connections": 5, "duration_days": 365,
        "is_free": True, "is_public": False, "is_renewable": False, "publish_layers": 3,
        "publish_daily_requests": 5000, "map_badge": True, "ows_projects": 1, "db_roles": 1, "team_members": 1,
        "backup_retention_days": 3, "description": "پایگاه داده دانشجویی پلن کلاس"})
    return plan


def teacher_contracts(user):
    """قراردادهای جاری که این کاربر استادشان است (شماره‌هایی که مدیر وارد کرده، با اولین ورود وصل می‌شوند)."""
    phone = getattr(user, "phone", None)
    if phone:
        for c in Contract.objects.filter(is_active=True, teacher_phones__contains=phone).exclude(teachers=user):
            if phone in {p.strip() for p in c.teacher_phones.splitlines()}:
                c.teachers.add(user)
    today = timezone.localdate()
    return Contract.objects.filter(teachers=user, is_active=True, starts_at__lte=today, ends_at__gte=today)


def create_class(user, contract: Contract, title: str, template: str, capacity: int, osm_area=None) -> Classroom:
    if not teacher_contracts(user).filter(pk=contract.pk).exists():
        raise ClassError("این قرارداد برای شما فعال نیست.")
    title = (title or "").strip()
    if not title:
        raise ClassError("عنوان کلاس را بنویسید.")
    if template not in Classroom.Template.values:
        raise ClassError("داده آغازین نامعتبر است.")
    if template == Classroom.Template.OSM and osm_area is None:
        raise ClassError("برای داده OSM یک شهر انتخاب کنید.")
    if capacity < 1:
        raise ClassError("ظرفیت باید دست‌کم یک نفر باشد.")
    if capacity > contract.free_seats:
        raise ClassError(f"فقط {contract.free_seats} صندلی خالی در این قرارداد مانده است.")
    return Classroom.objects.create(contract=contract, teacher=user, title=title[:150], template=template,
                                    capacity=capacity, osm_area=osm_area)


def term_end(contract: Contract) -> datetime:
    return timezone.make_aware(datetime.combine(contract.ends_at, time(23, 59)))


def join(classroom: Classroom, user, full_name: str, student_no: str = "") -> tuple[Enrollment, str]:
    """پایگاه داده دانشجو را می‌سازد؛ (ثبت‌نام، رمز یک‌بار نمایش)."""
    full_name = (full_name or "").strip()
    if not full_name:
        raise ClassError("نام و نام خانوادگی را بنویسید.")
    if classroom.teacher_id == user.pk:
        raise ClassError("استاد کلاس نمی‌تواند خودش ثبت‌نام کند.")
    existing = Enrollment.objects.filter(classroom=classroom, student=user).first()
    if existing:
        raise ClassError("قبلاً در این کلاس ثبت‌نام کرده‌اید.")
    with transaction.atomic():
        contract = Contract.objects.select_for_update().get(pk=classroom.contract_id)
        if classroom.status != Classroom.Status.ACTIVE or not classroom.is_open or not contract.is_current:
            raise ClassError("ثبت‌نام این کلاس بسته است.")
        if classroom.enrollments.count() >= classroom.capacity:
            raise ClassError("ظرفیت کلاس پر شده است؛ به استاد خبر دهید.")
        if contract.free_seats <= 0:
            raise ClassError("صندلی‌های قرارداد این کلاس تمام شده است؛ به استاد خبر دهید.")
        enrollment = Enrollment.objects.create(classroom=classroom, student=user, full_name=full_name[:120],
                                               student_no=(student_no or "").strip()[:30])
    password = generate_password()
    label = f"c{classroom.pk}_s{user.pk}"
    try:
        db = db_services.create_database(user, label, password, ["postgis"], plan=class_plan(contract.quota_mb),
                                         ignore_limit=True)
    except db_services.ServiceError as exc:
        enrollment.delete()
        raise ClassError(str(exc)) from exc
    db.expires_at = term_end(contract)
    db.save(update_fields=["expires_at"])
    enrollment.database = db
    enrollment.save(update_fields=["database"])
    # استاد پایگاه داده هر دانشجو را می‌بیند (برای نمره‌دادن)، بی‌آنکه از سهمیه تیم کم شود
    Member.objects.get_or_create(database=db, phone=classroom.teacher.phone or f"t{classroom.teacher_id}",
                                 defaults={"user": classroom.teacher, "role": Member.Role.VIEWER})
    seed(classroom, db, user)
    return enrollment, password


def seed(classroom: Classroom, db: UserDatabase, user) -> None:
    from databases import gdal

    if classroom.template == Classroom.Template.SAMPLE:
        for name in SAMPLE_LAYERS:
            try:
                gdal.import_layer(db, SAMPLE_DIR / f"{name}.geojson",
                                  {"name": name, "table": name, "mode": "create", "geom_type": ""}, None)
            except gdal.GdalError:
                log.exception("class seed %s", name)
    elif classroom.template == Classroom.Template.OSM and classroom.osm_area:
        from iranmap import ready

        try:
            ready.request_import(db, user, classroom.osm_area, ["roads", "pois", "buildings", "landuse"],
                                 ready.routing_allowed(classroom.osm_area) and ready.pgrouting_available(db))
        except ready.ReadyError as exc:
            log.warning("class osm seed: %s", exc)


def archive(classroom: Classroom) -> int:
    """پایان ترم: از پایگاه داده هر دانشجو بکاپ ۱۸۰روزه گرفته می‌شود؛ خود پایگاه‌ها با انقضا بسته می‌شوند."""
    n = 0
    for e in classroom.enrollments.select_related("database"):
        db = e.database
        if db is None or db.status not in UserDatabase.LIVE_STATUSES or e.archive_id:
            continue
        e.archive = Job.objects.create(kind=Job.Kind.BACKUP, trigger=Job.Trigger.SYSTEM, database=db,
                                       params={"archive": True, "classroom": classroom.pk})
        e.save(update_fields=["archive"])
        n += 1
    classroom.status = Classroom.Status.ARCHIVED
    classroom.is_open = False
    classroom.archived_at = timezone.now()
    classroom.save(update_fields=["status", "is_open", "archived_at"])
    return n


def tick(now=None) -> int:
    """کلاس‌هایی که ترمشان تمام شده (روز آخر، پیش از انقضای پایگاه داده‌ها در ۲۳:۵۹)."""
    now = timezone.localtime(now or timezone.now())
    if now.hour < 22:
        return 0
    n = 0
    for c in Classroom.objects.filter(status=Classroom.Status.ACTIVE, contract__ends_at__lte=now.date()):
        archive(c)
        n += 1
    return n


# ---------------------------------------------------------------- تمرین‌ها

FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٫", "0123456789.")


def _num(raw) -> str:
    return str(raw or "").strip().translate(FA_DIGITS).replace(",", ".")


def _due(days: str, day: str, keep: datetime | None) -> datetime | None:
    """مهلت: تاریخ دقیق (آخر همان روز)، یا چند روز از امروز، یا بدون مهلت؛ «keep» مقدار قبلی را نگه می‌دارد."""
    day, days = _num(day), _num(days)
    if day:
        try:
            d = date.fromisoformat(day)
        except ValueError as exc:
            raise ClassError("تاریخ مهلت معتبر نیست.") from exc
        return timezone.make_aware(datetime.combine(d, time(23, 59)))
    if days == "keep":
        return keep
    if days:
        if not days.isdigit() or not 0 < int(days) <= 365:
            raise ClassError("مهلت را بین ۱ تا ۳۶۵ روز بدهید.")
        return timezone.make_aware(datetime.combine(timezone.localdate() + timedelta(days=int(days)), time(23, 59)))
    return None


def save_assignment(classroom: Classroom, data, assignment: Assignment | None = None) -> Assignment:
    """ساخت یا ویرایش تمرین؛ data مثل request.POST است."""
    if classroom.status != Classroom.Status.ACTIVE:
        raise ClassError("کلاس بایگانی شده و تمرین تازه نمی‌پذیرد.")
    title = (data.get("title") or "").strip()
    if not title:
        raise ClassError("عنوان تمرین را بنویسید.")
    try:
        max_score = int(_num(data.get("max_score")) or 20)
    except ValueError as exc:
        raise ClassError("سقف نمره را عدد بنویسید.") from exc
    if not 1 <= max_score <= 1000:
        raise ClassError("سقف نمره باید بین ۱ تا ۱۰۰۰ باشد.")
    class_map = None
    if data.get("class_map"):
        class_map = ClassMap.objects.filter(classroom=classroom, pk=_num(data.get("class_map")) or 0).first()
        if class_map is None:
            raise ClassError("نقشه همراه باید از نقشه‌های اشتراکی همین کلاس باشد.")
    a = assignment or Assignment(classroom=classroom)
    a.title = title[:150]
    a.body = (data.get("body") or "").strip()[:8000]
    a.max_score = max_score
    a.class_map = class_map
    a.due_at = _due(data.get("due_days", ""), data.get("due_date", ""), a.due_at if assignment else None)
    a.is_published = data.get("is_published") in ("1", "on", "true", True)
    a.save()
    return a


def submit(assignment: Assignment, enrollment: Enrollment, note: str, webmap_id=None) -> Submission:
    """تحویل (یا تحویل دوباره) دانشجو؛ پس از نمره‌دادن فقط با «برگشت برای اصلاح» دوباره باز می‌شود."""
    classroom = assignment.classroom
    if enrollment.classroom_id != classroom.pk:
        raise ClassError("این تمرین مال کلاس شما نیست.")
    if classroom.status != Classroom.Status.ACTIVE or not assignment.is_published:
        raise ClassError("تحویل این تمرین بسته است.")
    if enrollment.database is None or not enrollment.database.is_live:
        raise ClassError("پایگاه داده شما فعال نیست؛ به استاد یا پشتیبانی خبر دهید.")
    sub = Submission.objects.filter(assignment=assignment, enrollment=enrollment).first()
    if sub and sub.status == Submission.Status.GRADED:
        raise ClassError("نمره‌ی این تمرین ثبت شده است؛ برای اصلاح از استاد بخواهید آن را برگرداند.")
    note = (note or "").strip()[:6000]
    webmap = None
    if webmap_id:
        from maps.models import WebMap

        webmap = WebMap.objects.filter(pk=_num(webmap_id) or 0, database=enrollment.database).first()
        if webmap is None:
            raise ClassError("نقشه‌ی انتخابی در پایگاه داده‌ی شما نیست.")
    if not note and webmap is None:
        raise ClassError("پاسخ را بنویسید یا نقشه‌ی تحویلی را انتخاب کنید.")
    sub = sub or Submission(assignment=assignment, enrollment=enrollment)
    sub.note, sub.webmap = note, webmap
    sub.status = Submission.Status.SUBMITTED
    sub.is_late = assignment.is_overdue
    sub.submitted_at = timezone.now()
    sub.save()
    return sub


def grade(sub: Submission, action: str, score_raw, feedback: str) -> Submission:
    """استاد نمره می‌دهد (action=grade) یا برای اصلاح برمی‌گرداند (action=return، با توضیح)."""
    feedback = (feedback or "").strip()[:6000]
    if sub.assignment.classroom.status != Classroom.Status.ACTIVE:
        raise ClassError("کلاس بایگانی شده است.")
    if action == "return":
        if not feedback:
            raise ClassError("بنویسید دانشجو چه چیزی را باید اصلاح کند.")
        sub.status = Submission.Status.RETURNED
        sub.score = None
    elif action == "grade":
        try:
            score = Decimal(_num(score_raw))
        except InvalidOperation as exc:
            raise ClassError("نمره را عدد بنویسید.") from exc
        if not 0 <= score <= sub.assignment.max_score:
            raise ClassError(f"نمره باید بین ۰ و {sub.assignment.max_score} باشد.")
        sub.score = score.quantize(Decimal("0.01"))
        sub.status = Submission.Status.GRADED
    else:
        raise ClassError("عمل نامعتبر است.")
    sub.feedback = feedback
    sub.graded_at = timezone.now()
    sub.save(update_fields=["score", "status", "feedback", "graded_at"])
    return sub


def roster(assignment: Assignment):
    """همه‌ی دانشجوهای کلاس با تحویل‌شان (یا None): [(enrollment, submission|None)]."""
    subs = {s.enrollment_id: s for s in assignment.submissions.all()}
    return [(e, subs.get(e.pk)) for e in assignment.classroom.enrollments.select_related("database", "student")]


def summary(assignment: Assignment, total: int | None = None) -> dict:
    """شمارنده‌ها برای فهرست: تحویل‌شده، نمره‌داده‌شده، برگشتی."""
    subs = list(assignment.submissions.all())
    total = assignment.classroom.enrollments.count() if total is None else total
    graded = sum(s.status == Submission.Status.GRADED for s in subs)
    returned = sum(s.status == Submission.Status.RETURNED for s in subs)
    return {"total": total, "submitted": len(subs), "graded": graded, "returned": returned,
            "waiting": len(subs) - graded - returned}
