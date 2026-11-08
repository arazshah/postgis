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

sys.path.insert(0, str(Path(__file__).resolve().parent))

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


def real_server():
    """سرور PostGIS واقعی (محلی) برای ویدیوهای مرورگر داده، SQL، نقشه و ..."""
    from databases.provisioner import Provisioner

    srv = DatabaseServer(name="demo", host=os.environ.get("PG_HOST", "localhost"), port=int(os.environ.get("PG_PORT", "5432")),
                         admin_user="postgres", sslmode="disable", public_host="db.postgis.ir", public_port=5439, is_default=True)
    srv.set_admin_password(os.environ.get("PG_PASSWORD", "postgres"))
    srv.save()
    Provisioner.for_server(srv).harden()
    return srv


NEIGH = [("ونک", 51.395, 35.760), ("تجریش", 51.430, 35.805), ("نارمک", 51.510, 35.735), ("شهرک غرب", 51.365, 35.765),
         ("جمهوری", 51.415, 35.700), ("هفت‌تیر", 51.425, 35.725)]


def init_main():
    """کاربر اصلی با پایگاه داده‌ی tehran_gis و داده‌ی نمونه (مدرسه، مترو، پارک، محله، مراکز درمانی)."""
    from databases import gdal
    from databases import services as dbs
    from databases.models import Plan

    call_command("migrate", verbosity=0)
    call_command("kb_sync", verbosity=0)  # مقاله‌ها برای دستیار
    from core.models import SiteSettings

    conf = SiteSettings.get()
    conf.sms_backend = "console"  # کد تأیید در ویدیو دیده می‌شود
    conf.survey_enabled = True
    conf.assistant_enabled, conf.assistant_base_url = True, f"http://127.0.0.1:{int(os.environ.get('PORT', '8765')) + 100}/v1"  # سرویس ساختگی (fake_llm.py)
    conf.set_assistant_api_key("demo")
    conf.pay_enabled, conf.pay_gateway_enabled, conf.gateway_sandbox = True, True, True  # صفحه‌ی پلن‌ها و فاکتور (پرداخت واقعی انجام نمی‌شود)
    conf.pay_manual_enabled, conf.pay_card_number, conf.pay_card_holder, conf.pay_bank_name = True, "6037991122334455", "شرکت نمونه", "ملی"
    conf.satgate_url = f"http://127.0.0.1:{int(os.environ.get('PORT', '8765')) + 334}"      # دروازه‌ی ساختگی (fake_satgate.py)
    conf.set_satgate_secret("demo-secret")
    conf.save()
    real_server()
    from databases.models import Plan as _Plan

    for i, (slug, name, mb, conn, price, days, maps) in enumerate((
            ("basic", "پایه", 5120, 10, 190000, 30, 5), ("pro", "حرفه‌ای", 25600, 25, 390000, 30, 20),
            ("org", "سازمانی", 102400, 60, 1290000, 30, 100))):
        _Plan.objects.update_or_create(slug=slug, defaults={
            "name": name, "quota_mb": mb, "max_connections": conn, "duration_days": days, "is_free": False,
            "price_toman": price, "is_public": True, "is_renewable": False, "order": 10 + i, "maps": maps,
            "publish_layers": 10 * (i + 1), "backup_retention_days": 7 * (i + 1), "team_members": 3 * (i + 1),
            "ows_projects": i + 1, "description": f"پلن {name}"})
    u = User.objects.create_user("09120000100")
    u.first_name, u.last_name = "علی", "رضایی"
    u.save()
    plan = Plan.objects.filter(is_default=True).first() or Plan.objects.filter(is_free=True).first()
    pw = "Demo-Pass-2026x"
    db = dbs.create_database(u, "tehran_gis", pw, ["postgis"], plan=plan)
    sample = Path(__file__).resolve().parents[2] / "classroom" / "sample"
    for name in ("schools", "metro_stations", "parks"):
        gdal.import_layer(db, sample / f"{name}.geojson", {"name": name, "table": name, "mode": "create", "geom_type": ""}, None)
    import psycopg

    with psycopg.connect(host=db.server.host, port=db.server.port, user=db.role_name, password=pw, dbname=db.db_name,
                         autocommit=True) as c:
        c.execute("CREATE TABLE neighborhoods (gid serial PRIMARY KEY, name text, population int, geom geometry(Polygon,4326))")
        for i, (n, x, y) in enumerate(NEIGH):
            c.execute("INSERT INTO neighborhoods(name,population,geom) VALUES (%s,%s,ST_MakeEnvelope(%s,%s,%s,%s,4326))",
                      (n, 18000 + i * 9500, x - .02, y - .02, x + .02, y + .02))
        c.execute("CREATE INDEX ON neighborhoods USING gist(geom)")
        c.execute("CREATE TABLE health_centers (gid serial PRIMARY KEY, name text, type text, beds int, geom geometry(Point,4326))")
        for i in range(40):
            c.execute("INSERT INTO health_centers(name,type,beds,geom) VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326))",
                      (f"مرکز {i + 1}", ["بیمارستان", "درمانگاه", "کلینیک"][i % 3], (i * 7) % 90, 51.33 + (i % 8) * .028, 35.68 + (i // 8) * .03))
        # قطعه‌های زمین کشاورزی (ویدیوی «تصویر ماهواره‌ای»)
        import satdemo

        c.execute("CREATE TABLE parcels (id text PRIMARY KEY, name text, geom geometry(Polygon,4326))")
        for pid, pname, ring in satdemo.parcels():
            c.execute("INSERT INTO parcels VALUES (%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326))",
                      (pid, pname, json.dumps({"type": "Polygon", "coordinates": [ring]})))
        c.execute("CREATE INDEX ON parcels USING gist(geom)")
    # «داده آماده ایران»: فهرست نواحی و یک فایل منبع خالی تا صفحه آماده نمایش باشد (واردکردن واقعی لازم نیست)
    from iranmap import osm as _osm
    from iranmap.models import Area

    _osm.source_file().touch()
    for name, level, prov, bb in (("تهران", "province", "", [50.3, 34.1, 53.0, 36.3]), ("تهران", "county", "تهران", [51.0, 35.5, 51.7, 35.9]),
                                  ("کرج", "county", "البرز", [50.8, 35.7, 51.1, 35.95]), ("اصفهان", "county", "اصفهان", [51.5, 32.5, 51.9, 32.8])):
        poly = {"type": "Polygon", "coordinates": [[[bb[0], bb[1]], [bb[2], bb[1]], [bb[2], bb[3]], [bb[0], bb[3]], [bb[0], bb[1]]]]}
        Area.objects.create(name=name, level=level, province=prov, bbox=bb, geometry=poly, population=8700000)
    f = User.objects.create_user("09120000101")  # کاربر تازه، بدون پایگاه داده (ویدیوی «ساخت پایگاه داده»)
    f.first_name, f.last_name = "مریم", "کریمی"
    f.save()
    OUT.write_text(json.dumps({"main": session(u), "fresh": session(f), "dbpw": pw, "dbid": db.pk}))


def plan(slug):
    """پلن پایگاه داده‌ی اصلی را عوض می‌کند (برای ویدیوهای سازمانی و برداشت میدانی)."""
    from databases.models import Plan

    p = Plan.objects.get(slug=slug)
    p.survey_projects, p.survey_max_points, p.gnss_external = 10, 100000, True
    p.dedicated_geoserver, p.raster_mb, p.clone_enabled, p.snapshot_hours = True, 2048, True, 6
    p.basemap_api, p.team_members, p.db_roles, p.maps, p.map_layers, p.map_charts = True, 10, 5, 50, 10, 10
    p.save()
    UserDatabase.objects.filter(owner__phone="09120000100").update(plan=p)


def serve():
    if os.environ.get("REAL_PG"):
        import fake_llm

        fake_llm.start(int(os.environ.get("PORT", "8765")) + 100)
        import fake_satgate

        port = int(os.environ.get("PORT", "8765"))
        fake_satgate.start(port + 334, f"http://localhost:{port}")
        call_command("runserver", os.environ.get("PORT", "8765"), "--noreload")
        return
    from classroom import services as cs

    def fake_create(user, label, password, exts, plan=None, ignore_limit=False, **kw):
        return fake_db(user, label)

    cs.db_services.create_database = fake_create
    cs.seed = lambda *a, **k: None
    call_command("runserver", os.environ.get("PORT", "8765"), "--noreload")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "init":
        prof = sys.argv[2]
        init_main() if prof == "main" else init(prof.removeprefix("classroom-"))
    elif cmd == "serve":
        serve()
    else:
        plan(sys.argv[2]) if cmd == "plan" else {"students": students, "submissions": submissions, "map": student_join_data, "returned": returned,
         "graded": graded}[cmd]()
