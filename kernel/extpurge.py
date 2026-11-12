"""پاک‌سازی صریح داده‌ی یک پلاگین سطح ۳ حذف‌شده (`manage.py ext_purge <id> --yes`)، پس از پشتیبان.

حذف پوشه‌ی پلاگین جدول‌هایش را نمی‌اندازد (بازگشت ممکن بماند). این‌جا فقط:
- جدول‌های `x_<id>_*` و ردیف‌های `django_migrations` با برچسب `x_<id>` پاک می‌شوند، نه چیز دیگر.
- اگر پلاگین هنوز نصب است (پوشه‌ی ext/<id>، در INSTALLED_APPS یا رجیستری) رد می‌شود.
- اگر پیشوند با پلاگین دیگری هم‌پوشان است (مثلاً purge «a» و جدول «x_a_b_*» از پلاگین «a_b»)، رد می‌شود.
"""
from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.db import connection, transaction

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


class PurgeError(Exception):
    pass


def plan(pid: str, root: Path | None = None) -> dict:
    """بررسی و فهرست آنچه پاک می‌شود؛ PurgeError اگر ایمن نیست. چیزی را تغییر نمی‌دهد."""
    from kernel.plugins import registry

    if not ID_RE.fullmatch(pid):
        raise PurgeError("شناسه‌ی نامعتبر.")
    label, prefix = f"x_{pid}", f"x_{pid}_"
    base = root or Path(settings.BASE_DIR) / "ext"
    if (base / pid).exists():
        raise PurgeError(f"پلاگین هنوز نصب است ({base / pid})؛ اول پوشه‌اش را در PR بردارید و استقرار دهید.")
    if f"ext.{pid}" in settings.INSTALLED_APPS or pid in registry.plugins:
        raise PurgeError("پلاگین هنوز در برنامه‌ی در حال اجرا بارگذاری شده است.")
    tables = sorted(t for t in connection.introspection.table_names() if t.startswith(prefix))
    with connection.cursor() as cur:
        cur.execute("SELECT DISTINCT app FROM django_migrations WHERE app = %s OR app LIKE %s", [label, label.replace("_", r"\_") + r"\_%"])
        apps = [r[0] for r in cur.fetchall()]
    clash = [a for a in apps if a != label]
    if clash:
        raise PurgeError(f"پیشوند با برچسب دیگری هم‌پوشان است ({', '.join(clash)})؛ با دست پاک کنید.")
    if not tables and not apps:
        raise PurgeError("چیزی برای پاک‌کردن نیست.")
    return {"label": label, "tables": tables, "migrations_app": label if apps else ""}


def execute(pid: str, root: Path | None = None) -> dict:
    p = plan(pid, root)
    q = connection.ops.quote_name
    with transaction.atomic(), connection.cursor() as cur:
        for t in p["tables"]:
            cur.execute(f"DROP TABLE IF EXISTS {q(t)} CASCADE")  # noqa: S608 - نام از introspection و پیشوند اعتبارسنجی‌شده
        cur.execute("DELETE FROM django_migrations WHERE app = %s", [p["label"]])
    return p
