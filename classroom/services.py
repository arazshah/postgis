"""ساخت کلاس، ثبت‌نام دانشجو (پایگاه داده جدا برای هر نفر) و بایگانی پایان ترم."""
from __future__ import annotations

import logging
from datetime import datetime, time
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from databases import services as db_services
from databases.crypto import generate_password
from databases.models import Member, Plan, UserDatabase
from jobs.models import Job

from .models import Classroom, Contract, Enrollment

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
