"""محیط نمایشی برای ضبط ویدیوهای راهنمای پلن کلاس (sqlite موقت؛ بدون سرور PostGIS).

استفاده (از ریشه‌ی مخزن، با DJANGO_TESTING=1 DJANGO_DEBUG=1 DATABASE_URL=sqlite:///...):
  python docs/help-video/demo.py init teacher|student   پایگاه نمایشی تازه + نشست‌ها (session.json)
  python docs/help-video/demo.py serve                  سرور روی ۸۷۶۵؛ ساخت پایگاه داده‌ی دانشجو جعلی است
  python docs/help-video/demo.py <مرحله>               داده‌ی بین صحنه‌ها (students، submissions، returned، graded، map)
"""
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()

from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import User  # noqa: E402
from classroom import services  # noqa: E402
from classroom.models import Classroom, Contract, Enrollment, Submission  # noqa: E402
from databases.models import DatabaseServer, UserDatabase  # noqa: E402

OUT = Path(__file__).with_name("session.json")
TEACHER, STUDENT = "09120000071", "09120000072"
NAMES = ["سارا احمدی", "علی رضایی", "مریم کریمی", "حسین موسوی", "نگار صادقی", "امیر حسینی", "زهرا طاهری"]
HW_BODY = ("ایستگاه‌های مترو را با ST_Buffer در فاصله‌ی ۵۰۰ متر بافر کنید و بگویید چند مدرسه در این محدوده است.\n"
           "جدول‌های ورودی: metro_stations و schools\nنام جدول خروجی: hw1_buffer")
SQL = "CREATE TABLE hw1_buffer AS\nSELECT ST_Buffer(geom::geography, 500)::geometry AS geom FROM metro_stations;"


def server():
    srv = DatabaseServer.objects.first()
    if srv is None:
        srv = DatabaseServer(name="demo", host="db.postgis.ir", port=5432, admin_user="postgres", sslmode="disable",
                             public_host="db.postgis.ir", is_default=True)
        srv.set_admin_password("x")
        srv.save()
    return srv


def fake_db(user, label, password=None):
    return UserDatabase.objects.create(owner=user, server=server(), plan=services.class_plan(500),
                                       db_name=f"gp_{label}", role_name=f"gp_{label}_u", status="active")


def session(user):
    ss = SessionStore()
    ss[SESSION_KEY], ss[HASH_SESSION_KEY] = str(user.pk), user.get_session_auth_hash()
    ss[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    ss.save()
    return ss.session_key


def cls():
    return Classroom.objects.order_by("-pk").first()


def init(role):
    call_command("migrate", verbosity=0)
    today = timezone.localdate()
    k = Contract.objects.create(institution="دانشگاه خواجه نصیرالدین طوسی", number="1405/237", seats=40,
                                starts_at=today, ends_at=today + timedelta(days=75), quota_mb=500,
                                teacher_phones=TEACHER)
    t, s = User.objects.create_user(TEACHER), User.objects.create_user(STUDENT)
    for u, n in ((t, "دکتر محمدی"), (s, "سارا احمدی")):
        u.first_name, u.last_name = n.split(" ", 1)
        u.save()
    if role == "student":
        c = services.create_class(t, k, "پایگاه داده مکانی — گروه ۱", "sample", 30)
        services.save_assignment(c, {"title": "تمرین ۱ — بافر ایستگاه‌های مترو", "body": HW_BODY, "max_score": "20",
                                     "due_days": "7", "is_published": "1"})
        services.save_assignment(c, {"title": "تمرین ۲ — نزدیک‌ترین پارک", "body": "برای هر مدرسه نزدیک‌ترین پارک را پیدا کنید.",
                                     "max_score": "20", "due_days": "14", "is_published": "1"})
        code = c.code
    else:
        code = ""
    OUT.write_text(json.dumps({"teacher": session(t), "student": session(s), "code": code}))


def students():
    c = cls()
    for i, n in enumerate(NAMES[1:], 2):
        u = User.objects.create_user(f"091200001{i:02d}")
        Enrollment.objects.create(classroom=c, student=u, full_name=n, student_no=f"40{i:02d}1",
                                  database=fake_db(u, f"c{c.pk}_s{u.pk}"))
    s = User.objects.get(phone=STUDENT)
    Enrollment.objects.create(classroom=c, student=s, full_name=NAMES[0], student_no="40011",
                              database=fake_db(s, f"c{c.pk}_s{s.pk}"))


def submissions():
    c = cls()
    a = c.assignments.first()
    notes = [SQL, "جدول hw1_buffer را ساختم؛ ۱۲ مدرسه در محدوده‌ی ۵۰۰ متری ایستگاه‌ها هست.",
             "SELECT count(*) FROM schools s JOIN metro_stations m ON ST_DWithin(s.geom::geography, m.geom::geography, 500);",
             "بافر را ساختم ولی تعداد مدرسه‌ها را حساب نکردم."]
    for e, note in zip(c.enrollments.order_by("pk"), notes, strict=False):
        services.submit(a, e, note)


def student_join_data():
    """بعد از ثبت‌نام دانشجو: یک نقشه برای تحویل و تحویل‌های دوستانش."""
    from maps.models import WebMap

    e = Enrollment.objects.get(student__phone=STUDENT)
    WebMap.objects.create(database=e.database, title="نقشه‌ی مترو و مدرسه‌ها", created_by=e.student)


def returned():
    sub = Submission.objects.get()
    services.grade(sub, "return", "", "جدول خروجی را با نام hw1_buffer بسازید و در پاسخ تعداد مدرسه‌های داخل بافر را هم بنویسید.")


def graded():
    sub = Submission.objects.get()
    services.grade(sub, "grade", "18", "عالی بود! فقط ایندکس مکانی روی خروجی را فراموش نکنید (GIST).")


def serve():
    from classroom import services as cs

    def fake_create(user, label, password, exts, plan=None, ignore_limit=False, **kw):
        return fake_db(user, label)

    cs.db_services.create_database = fake_create
    cs.seed = lambda *a, **k: None
    call_command("runserver", "8765", "--noreload")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "init":
        init(sys.argv[2].removeprefix("classroom-"))
    elif cmd == "serve":
        serve()
    else:
        {"students": students, "submissions": submissions, "map": student_join_data, "returned": returned,
         "graded": graded}[cmd]()
