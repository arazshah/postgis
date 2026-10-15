"""دسترسی به لایه‌های منتشرشده: لایه عمومی، کلید API، مالک وارد شده، و سقف درخواست روزانه."""
from __future__ import annotations

import base64
from datetime import timedelta

from django.db import connection
from django.utils import timezone

from databases.models import UserDatabase

from .models import ApiKey


class Denied(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def raw_key(request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if auth.lower().startswith("basic "):
        try:
            _user, _, password = base64.b64decode(auth[6:].strip()).decode().partition(":")
            return password.strip()
        except (ValueError, UnicodeDecodeError):
            return ""
    return (request.headers.get("X-API-Key") or request.GET.get("key") or "").strip()


def key_for(request, db: UserDatabase) -> ApiKey | None:
    raw = raw_key(request)
    if not raw.startswith(ApiKey.PREFIX):
        return None
    key = ApiKey.objects.filter(key_hash=ApiKey.digest(raw), revoked_at__isnull=True, database=db).first()
    if key and (key.last_used_at is None or timezone.now() - key.last_used_at > timedelta(minutes=5)):
        ApiKey.objects.filter(pk=key.pk).update(last_used_at=timezone.now())
    return key


def is_owner(request, db: UserDatabase) -> bool:
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.pk == db.owner_id)


def full_access(request, db: UserDatabase) -> bool:
    """مالک وارد شده یا کلید API معتبر همین پایگاه داده: لایه‌های خصوصی را هم می‌بیند."""
    return is_owner(request, db) or key_for(request, db) is not None


def check_database(db: UserDatabase):
    if db.status not in UserDatabase.LIVE_STATUSES:
        raise Denied(403, "Unavailable", "این پایگاه داده فعال نیست (منقضی، معلق یا حذف‌شده).")


def check_layer(request, layer) -> bool:
    """خطا می‌دهد اگر دسترسی نیست؛ خروجی: آیا درخواست از مالک خود سایت است (شمارش نمی‌شود)."""
    db = layer.service.database
    check_database(db)
    owner = is_owner(request, db)
    if layer.is_public or owner:
        return owner
    if raw_key(request) == "":
        raise Denied(401, "Unauthorized", "این لایه خصوصی است؛ کلید API را بفرستید (?key= یا هدر Authorization).")
    if key_for(request, db) is None:
        raise Denied(403, "Forbidden", "کلید API نامعتبر است، باطل شده یا مال این پایگاه داده نیست.")
    return False


def count(db: UserDatabase) -> int:
    """یک درخواست به مصرف امروز اضافه می‌کند؛ اگر از سقف پلن گذشت خطای 429."""
    day = timezone.localdate()
    with connection.cursor() as cur:
        cur.execute("""
            INSERT INTO publish_dailyusage (database_id, day, requests) VALUES (%s, %s, 1)
            ON CONFLICT (database_id, day) DO UPDATE SET requests = publish_dailyusage.requests + 1
            RETURNING requests
        """, [db.pk, day])
        used = cur.fetchone()[0]
    cap = db.plan.publish_daily_requests
    if cap and used > cap:
        raise Denied(429, "TooManyRequests",
                     f"سقف {cap} درخواست روزانه این پایگاه داده پر شده است. فردا دوباره باز می‌شود یا پلن را ارتقا دهید.")
    return used


def usage_today(db: UserDatabase) -> int:
    from .models import DailyUsage

    row = DailyUsage.objects.filter(database=db, day=timezone.localdate()).first()
    return row.requests if row else 0
