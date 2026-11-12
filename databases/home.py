"""سهم پلاگین پایگاه داده در صفحه‌ی خانه: ادامه‌ی کار (ورود و بکاپ) و گام‌های نخست چک‌لیست."""
from django.urls import reverse

from jobs.models import Job
from kernel import routes


def feed(user, dbs):
    rows = []
    for j in Job.objects.filter(database__in=dbs, status=Job.Status.DONE,
                                kind__in=[Job.Kind.IMPORT, Job.Kind.BACKUP]).select_related("database").order_by("-created_at")[:4]:
        rows.append({"icon": "upload" if j.kind == Job.Kind.IMPORT else "save", "kind": j.get_kind_display(),
                     "text": j.get_kind_display() + " انجام شد", "db": j.database.db_name, "when": j.created_at,
                     "url": reverse("databases:explore" if j.kind == Job.Kind.IMPORT else "databases:backups", args=[j.database_id])})
    return rows


def step_profile(user, dbs, target):
    return {"label": "پروفایل را کامل کنید", "hint": "نام و دانشگاه / شرکت", "done": bool(user.full_name and user.organization),
            "url": reverse("accounts:profile"), "icon": "user"}


def step_create(user, dbs, target):
    return {"label": "پایگاه داده بسازید", "hint": "کمتر از یک دقیقه", "done": bool(dbs), "url": reverse("databases:create"),
            "icon": "db"}


def step_import(user, dbs, target):
    has_data = bool(dbs) and Job.objects.filter(database__in=dbs, kind=Job.Kind.IMPORT, status=Job.Status.DONE).exists()
    return {"label": "اولین داده را وارد کنید", "hint": "فایل مکانی آپلود کنید", "done": has_data,
            "url": reverse("databases:import", args=[target.pk]) if target and routes.on("databases:import", user=user, ws=target) else "",
            "icon": "upload"}
