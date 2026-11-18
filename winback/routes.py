"""تعریف مسیرهای بازگشت: چه کسانی، با چه پیامی (قالب sms.ir) و به کجا می‌رسند.

هر مسیر یک گروه از رفتار کاربر است (نه یک کمپین همگانی). پیام از داده‌ی خود کاربر ساخته می‌شود و به صفحه‌ی درست می‌رسد.
متن قالب را مدیر در sms.ir می‌سازد؛ پارامترها با `#NAME#` در متن می‌آیند. `NAME`، `LINK` و `STOP` همیشه هستند.
"""
from __future__ import annotations

import datetime
import re
from collections.abc import Callable
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q
from django.urls import reverse
from django.utils import timezone

COMMON = ("NAME", "LINK", "STOP")


@dataclass(frozen=True)
class RouteDef:
    key: str
    title: str
    goal: str
    template: str
    extra: tuple[str, ...]
    pick: Callable[[datetime.datetime], list]  # (now) -> [(user, {param: value}, dest, gift_db_id|None)]
    cooldown_days: int = 30
    variant_b: str = ""  # متن جایگزین برای آزمون A/B (همان پارامترها)
    manual_only: bool = False  # فهرست شبانه نمی‌سازد؛ فقط از «ارسال دستی»
    extra_input: str = ""  # پارامتری که مدیر هنگام ارسال دستی تایپ می‌کند (مثلاً FEATURE)
    # --- ایمیل (ADR-0012 فاز ۴): متن‌ها با همان جای‌نگهدارهای #NAME# و … ساخته می‌شوند
    email_subject: str = ""
    email_subject_b: str = ""
    email_body: str = ""  # هر خط یک بند
    email_cta: str = "ادامه"
    channels: tuple[str, ...] = ("sms", "email", "both", "email_sms")  # کانال‌های مجاز برای این مسیر

    def text(self, variant: str = "A") -> str:
        """متن قالب با دامنه‌ی سایت (sms.ir دامنه‌ی ثابت می‌خواهد؛ فقط انتهای لینک متغیر است)."""
        raw = self.variant_b if variant == "B" and self.variant_b else self.template
        return raw.replace("{SITE}", site())

    @property
    def params(self) -> tuple[str, ...]:
        return COMMON + self.extra


def site() -> str:
    """دامنه‌ی ثابت لینک در قالب پیامک (بدون http؛ از CANONICAL_URL)."""
    from urllib.parse import urlsplit

    from django.conf import settings

    return urlsplit(settings.CANONICAL_URL).netloc


def first_name(user) -> str:
    return ((user.full_name or "").split() or ["دوست"])[0][:18]


def render(template: str, params: dict) -> str:
    """پیش‌نمایش متن نهایی (همان جایگزینی که sms.ir انجام می‌دهد)."""
    return re.sub(r"#([A-Z_]+)#", lambda m: str(params.get(m.group(1), m.group(0))), template)


def segments(text: str) -> int:
    """تعداد بخش پیامک فارسی (۷۰ نویسه‌ی اول، سپس ۶۷ تا ۶۷ تا)."""
    n = len(text)
    return 1 if n <= 70 else -(-n // 67)


def _users():
    """کاربر سایت با دست‌کم یک کانال تأییدشده (موبایل یا ایمیل)؛ انتخاب کانال هر مسیر بعداً در `channel_for` است."""
    User = get_user_model()
    return User.objects.filter(is_active=True, is_staff=False, analytics_exclude=False).filter(
        Q(phone__isnull=False, phone_verified_at__isnull=False) | Q(email__isnull=False, email_verified_at__isnull=False))


def has_sms(user) -> bool:
    return bool(user.phone and user.phone_verified_at)


def has_email(user) -> bool:
    return bool(user.email and user.email_verified_at)


def channel_for(user, wanted: str) -> str | None:
    """برنامه‌ی مؤثر کانال برای این کاربر؛ None اگر کانال لازمِ مسیر را ندارد (مثلاً مسیر ایمیلیِ کاربر بی‌ایمیل)."""
    s, e = has_sms(user), has_email(user)
    if wanted == "sms":
        return "sms" if s else None
    if wanted == "email":
        return "email" if e else None
    if s and e:
        return wanted
    return "sms" if s else ("email" if e else None)


def _db():
    from databases.models import UserDatabase

    return UserDatabase


def _days_between(now, lo: int, hi: int):
    return now - datetime.timedelta(days=hi), now - datetime.timedelta(days=lo)


def _no_database(now):
    a, b = _days_between(now, 2, 30)
    UserDatabase = _db()
    has_db = UserDatabase.objects.filter(owner=OuterRef("pk")).exclude(status=UserDatabase.Status.DELETED)
    qs = _users().filter(date_joined__gte=a, date_joined__lte=b).exclude(Exists(has_db))
    return [(u, {}, reverse("databases:create"), None) for u in qs]


def _empty_database(now):
    from analytics.models import Event

    a, b = _days_between(now, 3, 30)
    UserDatabase = _db()
    imported = Event.objects.filter(visitor__user=OuterRef("owner"), name=Event.IMPORT_QUEUED)
    dbs = (UserDatabase.objects.filter(status__in=UserDatabase.LIVE_STATUSES, created_at__gte=a, created_at__lte=b,
                                       owner__in=_users())
           .exclude(Exists(imported)).select_related("owner").order_by("owner_id", "created_at"))
    seen, out = set(), []
    for d in dbs:
        if d.owner_id in seen:
            continue
        seen.add(d.owner_id)
        out.append((d.owner, {"DB": d.label[:20]}, reverse("databases:detail", args=[d.pk]), d.pk))
    return out


def _dormant(now):
    from django.db.models.functions import Coalesce

    a, b = _days_between(now, 30, 120)
    UserDatabase = _db()
    live = UserDatabase.objects.filter(owner=OuterRef("pk"), status__in=UserDatabase.LIVE_STATUSES)
    qs = (_users().annotate(seen=Coalesce("last_login", "date_joined")).filter(seen__gte=a, seen__lte=b)
          .filter(Exists(live)))
    out = []
    for u in qs:
        d = UserDatabase.objects.filter(owner=u, status__in=UserDatabase.LIVE_STATUSES).order_by("-created_at").first()
        days = max((now - u.seen).days, 1)
        out.append((u, {"DB": d.label[:20], "DAYS": str(days)}, reverse("databases:detail", args=[d.pk]), d.pk))
    return out


def _expired_plan(now):
    a, b = _days_between(now, 1, 14)
    UserDatabase = _db()
    dbs = (UserDatabase.objects.filter(expires_at__gte=a, expires_at__lte=b, owner__in=_users(),
                                       status__in=[*UserDatabase.LIVE_STATUSES, UserDatabase.Status.EXPIRED])
           .select_related("owner", "plan").order_by("owner_id", "-expires_at"))
    seen, out = set(), []
    for d in dbs:
        if d.owner_id in seen or not d.plan.is_renewable:
            continue
        seen.add(d.owner_id)
        out.append((d.owner, {"DB": d.label[:20], "DAYS": str(max((now - d.expires_at).days, 1))},
                    reverse("databases:renew", args=[d.pk]), d.pk))
    return out


def _unpaid_invoice(now):
    from billing.models import Invoice

    a, b = _days_between(now, 2, 10)
    paid_later = Invoice.objects.filter(user=OuterRef("user"), status=Invoice.Status.PAID, created_at__gte=OuterRef("created_at"))
    inv = (Invoice.objects.filter(status__in=[Invoice.Status.PENDING, Invoice.Status.EXPIRED], created_at__gte=a, created_at__lte=b,
                                  user__in=_users())
           .exclude(Exists(paid_later)).select_related("user").order_by("user_id", "-created_at"))
    seen, out = set(), []
    for i in inv:
        if i.user_id in seen:
            continue
        seen.add(i.user_id)
        out.append((i.user, {"AMOUNT": f"{i.amount_toman:,}"}, reverse("billing:invoice", args=[i.number]), None))
    return out


def _announce(now):
    from django.db.models.functions import Coalesce

    UserDatabase = _db()
    live = UserDatabase.objects.filter(owner=OuterRef("pk"), status__in=UserDatabase.LIVE_STATUSES)
    qs = (_users().annotate(seen=Coalesce("last_login", "date_joined")).filter(seen__gte=now - datetime.timedelta(days=90))
          .filter(Exists(live)))
    return [(u, {}, "/plugins/", None) for u in qs]


def _fmt_size(n: int) -> str:
    mb = n / (1024 * 1024)
    return f"{mb / 1024:.1f} گیگابایت" if mb >= 1024 else f"{mb:.1f} مگابایت"


def _tip(pct: int, size: int) -> str:
    if pct >= 80:
        return "حجم پایگاه به سقف نزدیک است؛ داده‌ی اضافه را پاک کنید یا پلن را ارتقا دهید تا فقط‌خواندنی نشود."
    if size < 1024 * 1024:
        return "پایگاه هنوز تقریباً خالی است؛ فایل CSV یا شیپ‌فایل‌تان را وارد کنید یا داده‌ی آماده‌ی ایران را با یک کلیک بگیرید."
    return "داده‌هایتان آماده است؛ با ابزارهای تحلیل بدون SQL یا استودیوی نقشه یک خروجی بسازید و منتشر کنید."


def _monthly_report(now):
    """گزارش ماهانه برای کم‌کارها (۱۰ تا ۹۰ روز بی‌ورود) با داده‌ی خود پنل (حجم، سهم سقف، پلن، انقضا)؛ فقط ایمیلی."""
    from django.db.models.functions import Coalesce

    a, b = _days_between(now, 10, 90)
    UserDatabase = _db()
    live = UserDatabase.objects.filter(owner=OuterRef("pk"), status__in=UserDatabase.LIVE_STATUSES)
    qs = (_users().filter(email__isnull=False, email_verified_at__isnull=False)
          .annotate(seen=Coalesce("last_login", "date_joined")).filter(seen__gte=a, seen__lte=b).filter(Exists(live)))
    out = []
    for u in qs:
        d = (UserDatabase.objects.filter(owner=u, status__in=UserDatabase.LIVE_STATUSES).select_related("plan")
             .order_by("-created_at").first())
        pct = min(round(d.size_bytes * 100 / d.quota_bytes), 100) if d.quota_bytes else 0
        out.append((u, {"DB": d.label[:30], "SIZE": _fmt_size(d.size_bytes), "PCT": str(pct), "PLAN": d.plan.name[:30],
                        "TIP": _tip(pct, d.size_bytes)}, reverse("databases:detail", args=[d.pk]), d.pk))
    return out


_TAIL = "\nلغو پیام‌ها: {SITE}/r/stop/#STOP#"

DEFS: dict[str, RouteDef] = {d.key: d for d in (
    RouteDef("no_database", "ثبت‌نام بدون شروع",
             "ثبت‌نام کرده‌اند ولی هنوز پایگاهی نساخته‌اند؛ ساخت پایگاه رایگان با یک کلیک.",
             "#NAME# عزیز، پایگاه PostGIS رایگان شما در postgis.ir فقط ۳۰ ثانیه تا آماده‌شدن فاصله دارد.\nساخت: {SITE}/r/#LINK#" + _TAIL,
             (), _no_database, variant_b="#NAME# عزیز، پایگاه PostGIS رایگان شما بدون نصب و تنظیم آماده‌ی ساخت است؛ فقط یک کلیک: {SITE}/r/#LINK#" + _TAIL,
             email_subject="پایگاه PostGIS رایگان شما فقط یک کلیک تا آماده‌شدن فاصله دارد",
             email_subject_b="#NAME#، پایگاه رایگانتان را بسازید",
             email_body="#NAME# عزیز، ثبت‌نام کرده‌اید ولی هنوز پایگاهی نساخته‌اید.\nساخت پایگاه PostGIS رایگان بدون نصب و تنظیم حدود ۳۰ ثانیه طول می‌کشد؛ بعد می‌توانید داده‌تان را وارد و نقشه بسازید.",
             email_cta="ساخت پایگاه رایگان"),
    RouteDef("empty_database", "پایگاه خالی",
             "پایگاه ساخته‌اند ولی داده‌ای وارد نکرده‌اند؛ پیشنهاد ورود داده (CSV، شیپ‌فایل یا داده‌ی آماده‌ی ایران).",
             "#NAME# عزیز، پایگاه «#DB#» شما آماده است ولی هنوز داده ندارد. فایل خود را بیندازید یا داده‌ی آماده‌ی ایران را با یک کلیک بگیرید: {SITE}/r/#LINK#" + _TAIL,
             ("DB",), _empty_database, variant_b="#NAME# عزیز، پایگاه «#DB#» خالی است. فایل CSV، شیپ‌فایل یا داده‌ی آماده‌ی ایران را در چند دقیقه وارد کنید: {SITE}/r/#LINK#" + _TAIL,
             email_subject="پایگاه «#DB#» آماده است؛ فقط داده می‌خواهد",
             email_subject_b="#NAME#، اولین داده‌تان را وارد کنید",
             email_body="#NAME# عزیز، پایگاه «#DB#» ساخته شده ولی هنوز داده‌ای ندارد.\nفایل CSV یا شیپ‌فایل‌تان را بیندازید یا داده‌ی آماده‌ی ایران را با یک کلیک بگیرید؛ چند دقیقه بیشتر طول نمی‌کشد.",
             email_cta="ورود داده"),
    RouteDef("dormant", "کاربر خوابیده",
             "۳۰ تا ۱۲۰ روز است وارد نشده‌اند و پایگاه فعال دارند؛ یادآوری داده‌ی سالم خودشان.",
             "#NAME# عزیز، #DAYS# روز است سری به پایگاه «#DB#» نزده‌اید. داده‌هایتان سالم و آماده است: {SITE}/r/#LINK#" + _TAIL,
             ("DB", "DAYS"), _dormant, variant_b="#NAME# عزیز، قابلیت‌های تازه‌ای از آخرین ورود شما به postgis.ir اضافه شده. پایگاه «#DB#» منتظر شماست: {SITE}/r/#LINK#" + _TAIL,
             email_subject="داده‌های پایگاه «#DB#» سالم و آماده‌اند",
             email_subject_b="#NAME#، #DAYS# روز است سر نزده‌اید",
             email_body="#NAME# عزیز، #DAYS# روز است به پایگاه «#DB#» سر نزده‌اید.\nداده‌هایتان سالم و آماده است؛ از آخرین ورود شما قابلیت‌های تازه‌ای هم اضافه شده.",
             email_cta="بازگشت به پایگاه"),
    RouteDef("expired_plan", "پلن تمام‌شده",
             "پلن پایگاه در دو هفته‌ی اخیر تمام شده؛ یادآوری صادقانه و تمدید.",
             "#NAME# عزیز، پلن پایگاه «#DB#» #DAYS# روز پیش تمام شد. داده‌های شما نگه داشته شده؛ تمدید: {SITE}/r/#LINK#" + _TAIL,
             ("DB", "DAYS"), _expired_plan, cooldown_days=14, variant_b="#NAME# عزیز، پایگاه «#DB#» هنوز نگه داشته شده ولی پلنش تمام شده. برای ادامه‌ی کار تمدید کنید: {SITE}/r/#LINK#" + _TAIL,
             email_subject="پلن پایگاه «#DB#» تمام شده؛ داده‌های شما نگه داشته شده",
             email_subject_b="#NAME#، پایگاه «#DB#» منتظر تمدید است",
             email_body="#NAME# عزیز، پلن پایگاه «#DB#» #DAYS# روز پیش تمام شد.\nداده‌های شما نگه داشته شده و با تمدید دوباره در دسترس‌اند.",
             email_cta="تمدید پلن"),
    RouteDef("unpaid_invoice", "فاکتور نیمه‌کاره",
             "فاکتوری ساخته‌اند ولی پرداخت نکرده‌اند.",
             "#NAME# عزیز، فاکتور #AMOUNT# تومانی شما در postgis.ir هنوز پرداخت نشده است. ادامه‌ی پرداخت: {SITE}/r/#LINK#" + _TAIL,
             ("AMOUNT",), _unpaid_invoice, cooldown_days=14, variant_b="#NAME# عزیز، فاکتور #AMOUNT# تومانی شما فقط یک قدم تا فعال‌شدن مانده است: {SITE}/r/#LINK#" + _TAIL,
             email_subject="فاکتور #AMOUNT# تومانی شما هنوز پرداخت نشده",
             email_subject_b="#NAME#، یک قدم تا فعال‌شدن پلن مانده",
             email_body="#NAME# عزیز، فاکتور #AMOUNT# تومانی شما در postgis.ir هنوز پرداخت نشده است.\nبا ادامه‌ی پرداخت، پلن شما بلافاصله فعال می‌شود.",
             email_cta="ادامه‌ی پرداخت"),
    RouteDef("monthly_report", "گزارش ماهانه‌ی پایگاه",
             "ایمیلِ ماهانه برای کاربرانی که ۱۰ تا ۹۰ روز بی‌ورودند و پایگاه فعال دارند: حجم، سهم سقف، پلن و یک پیشنهاد مناسب وضعیت پایگاه.",
             "", ("DB", "SIZE", "PCT", "PLAN", "TIP"), _monthly_report, cooldown_days=30,
             email_subject="گزارش ماهانه‌ی پایگاه «#DB#»",
             email_subject_b="#NAME#، وضعیت پایگاه «#DB#» این ماه",
             email_body="#NAME# عزیز، گزارش این ماه پایگاه «#DB#»:\nحجم مصرفی: #SIZE# (#PCT#٪ سقف پلن #PLAN#)\n#TIP#",
             email_cta="رفتن به پایگاه", channels=("email",)),
    RouteDef("announce", "خبر قابلیت تازه",
             "ارسال دستی: معرفی یک قابلیت یا پلاگین تازه به کاربران فعال ۹۰ روز اخیر که پایگاه دارند.",
             "#NAME# عزیز، قابلیت تازه‌ی postgis.ir: #FEATURE#. ببینید: {SITE}/r/#LINK#" + _TAIL,
             ("FEATURE",), _announce, cooldown_days=14, manual_only=True, extra_input="FEATURE",
             email_subject="تازه در postgis.ir: #FEATURE#",
             email_body="#NAME# عزیز، قابلیت تازه‌ی postgis.ir: #FEATURE#.\nبرای دیدن جزئیات و امتحان آن روی دکمه‌ی زیر بزنید.",
             email_cta="دیدن قابلیت تازه"),
)}


def name_of(key: str) -> str:
    d = DEFS.get(key)
    return d.title if d else key


def now() -> datetime.datetime:
    return timezone.now()
