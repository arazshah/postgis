"""
دسترسی چندنفره به یک پایگاه داده.

- سطح‌ها: مالک (۳) > ویرایشگر (۲) > مشاهده‌گر (۱).
- مشاهده‌گر: مرورگر جدول‌ها، SQL فقط‌خواندنی، خروجی گرفتن، دیدن نقشه‌های خصوصی.
- ویرایشگر: به‌علاوه SQL با تغییر، ورود فایل، داده آماده، اصلاح سلامت داده، انتشار لایه و WMS/WFS.
- فقط مالک: رمز، افزونه، تمدید و پرداخت، حذف، بکاپ و بازگردانی، کلید API، کاربران و اعضای تیم.
"""
from __future__ import annotations

import re

from django.db import transaction
from django.http import Http404

from .models import ActivityLog, DbRole, Member, UserDatabase

VIEWER, EDITOR, OWNER = 1, 2, 3
LEVELS = {"viewer": VIEWER, "editor": EDITOR, "owner": OWNER}
PHONE_RE = re.compile(r"^09\d{9}$")
SUFFIX_RE = re.compile(r"^[a-z][a-z0-9]{1,11}$")
RESERVED = {"web", "ows", "user", "admin", "postgres", "owner"}


class TeamError(Exception):
    pass


def level(user, db: UserDatabase) -> int:
    if not (user and user.is_authenticated):
        return 0
    if db.owner_id == user.pk:
        return OWNER
    m = Member.objects.filter(database=db, user=user).only("role").first()
    if m is None and getattr(user, "phone", None):
        # دعوتی که پیش از ثبت‌نام این شماره فرستاده شده بود
        if Member.objects.filter(database=db, user__isnull=True, phone=user.phone).update(user=user):
            m = Member.objects.filter(database=db, user=user).only("role").first()
    if m is None:
        return 0
    return EDITOR if m.role == Member.Role.EDITOR else VIEWER


def get_db(request, pk, need: str = "owner", qs=None) -> UserDatabase:
    qs = qs if qs is not None else UserDatabase.objects.select_related("server", "plan")
    db = qs.exclude(status=UserDatabase.Status.DELETED).filter(pk=pk).first()
    if db is None:
        raise Http404
    lvl = level(request.user, db)
    if lvl < LEVELS[need]:
        raise Http404
    db.my_level = lvl
    db.is_mine = lvl == OWNER
    db.can_edit = lvl >= EDITOR
    return db


def link_pending(user) -> int:
    """دعوت‌هایی که پیش از ثبت‌نام با همین شماره فرستاده شده‌اند."""
    phone = getattr(user, "phone", "") or ""
    if not PHONE_RE.match(phone):
        return 0
    return Member.objects.filter(user__isnull=True, phone=phone).update(user=user)


def shared_with(user):
    return (UserDatabase.objects.filter(members__user=user).exclude(status=UserDatabase.Status.DELETED)
            .select_related("owner", "plan").distinct())


# ---------------------------------------------------------------------- اعضای تیم
def invite(db: UserDatabase, by, phone: str, role: str) -> Member:
    from django.core.exceptions import ValidationError

    from accounts.models import User, normalize_mobile

    try:
        phone = normalize_mobile(phone or "")
    except ValidationError as exc:
        raise TeamError("شماره موبایل را به شکل ۰۹۱۲۱۲۳۴۵۶۷ بنویسید.") from exc
    if role not in Member.Role.values:
        raise TeamError("نقش نامعتبر است.")
    if phone == db.owner.phone:
        raise TeamError("این شماره خود مالک پایگاه داده است.")
    cap = db.plan.team_members
    if cap == 0:
        raise TeamError("اشتراک با اعضای تیم در پلن‌های پولی فعال است.")
    if db.members.count() >= cap and not db.members.filter(phone=phone).exists():
        raise TeamError(f"پلن این پایگاه داده حداکثر {cap} عضو تیم دارد.")
    user = User.objects.filter(phone=phone).first()
    m, created = Member.objects.update_or_create(database=db, phone=phone,
                                                 defaults={"role": role, "user": user, "invited_by": by})
    ActivityLog.objects.create(user=by, database=db, action="team_invite",
                               message=f"{'دعوت' if created else 'تغییر نقش'} {phone} ({m.get_role_display()})")
    return m


def remove_member(db: UserDatabase, by, member: Member) -> None:
    ActivityLog.objects.create(user=by, database=db, action="team_remove", message=f"حذف عضو {member.phone}")
    member.delete()


# ---------------------------------------------------------------------- کاربران PostgreSQL
def role_name_for(db: UserDatabase, suffix: str) -> str:
    return f"{db.role_name[:50]}_{suffix}"


def create_role(db: UserDatabase, by, suffix: str, access: str, password: str, note: str = "") -> DbRole:
    from .services import limits_for, provisioner_for

    suffix = (suffix or "").strip().lower()
    if not SUFFIX_RE.match(suffix) or suffix in RESERVED:
        raise TeamError("نام کوتاه: ۲ تا ۱۲ حرف و رقم لاتین کوچک، با حرف شروع شود (مثلاً reader یا geoserver).")
    if access not in DbRole.Access.values:
        raise TeamError("سطح دسترسی نامعتبر است.")
    if not db.is_live:
        raise TeamError("پایگاه داده فعال نیست.")
    cap = db.plan.db_roles
    if db.db_roles.count() >= cap:
        raise TeamError(f"پلن این پایگاه داده حداکثر {cap} کاربر اضافه دارد.")
    name = role_name_for(db, suffix)
    if DbRole.objects.filter(name=name).exists() or UserDatabase.objects.filter(role_name=name).exists():
        raise TeamError("این نام قبلاً استفاده شده است؛ نام دیگری انتخاب کنید.")
    with transaction.atomic():
        role = DbRole.objects.create(database=db, name=name, access=access, note=note[:120], created_by=by)
        provisioner_for(db.server).create_extra_role(db.db_name, db.role_name, name, password,
                                                     write=access == DbRole.Access.WRITE,
                                                     limits=limits_for(db.plan))
    ActivityLog.objects.create(user=by, database=db, action="role_create",
                               message=f"کاربر {name} ({role.get_access_display()})")
    return role


def reset_role_password(db: UserDatabase, by, role: DbRole, password: str) -> None:
    from .services import provisioner_for

    provisioner_for(db.server).set_password(role.name, password)
    ActivityLog.objects.create(user=by, database=db, action="role_password", message=f"رمز جدید برای {role.name}")


def drop_role(db: UserDatabase, by, role: DbRole) -> None:
    from .services import provisioner_for

    provisioner_for(db.server).drop_extra_role(db.db_name, role.name)
    ActivityLog.objects.create(user=by, database=db, action="role_drop", message=f"حذف کاربر {role.name}")
    role.delete()
