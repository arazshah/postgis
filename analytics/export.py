"""خروجی اکسل کامل از رفتار کاربران و وضعیت سایت (برای تحلیل بیرونی).

هر برگه یک جدول تخت است (سطر = یک رویداد یا موجودیت) تا در Excel با فیلتر و Pivot کار کند.
شماره موبایل ناقص (۰۹۱۲***۴۵۶۷) نوشته می‌شود؛ متن پرسش‌ها، رمزها، کلیدها و محتوای فرم‌ها هرگز در خروجی نیست.
"""
from __future__ import annotations

import io
import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta

import jdatetime
import xlsxwriter
from django.db.models import Count, Max, Min, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from . import reports
from .models import Event, TrackedLink, Visit, Visitor

MAX_ROWS = 200_000  # سقف سطر هر برگه؛ Excel تا ۱٬۰۴۸٬۵۷۶ سطر را می‌پذیرد ولی فایل سنگین می‌شود
PHONE_RE = re.compile(r"(?<!\d)(09\d{2})\d{3}(\d{4})(?!\d)")

EVENT_LABELS = {
    Event.OTP_REQUESTED: "درخواست کد ورود", Event.OTP_SEND_FAILED: "ارسال پیامک ناموفق", Event.OTP_WRONG: "کد اشتباه",
    Event.OTP_VERIFIED: "ورود کد صحیح", Event.SIGNUP: "ثبت‌نام جدید", Event.LOGIN: "ورود",
    Event.DB_CREATED: "ساخت پایگاه داده", Event.IMPORT_QUEUED: "ورود داده (در صف)", Event.MAP_VIEWED: "دیدن نقشه جدول",
}


def mask_phone(value: str | None) -> str:
    return PHONE_RE.sub(r"\1***\2", value or "")


def local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return timezone.localtime(dt).replace(tzinfo=None) if timezone.is_aware(dt) else dt


def jalali(dt: datetime | date | None, time: bool = True) -> str:
    """تاریخ شمسی با رقم لاتین (۱۴۰۵/۰۸/۰۹ ۱۴:۳۵)؛ مرتب‌شدنی به‌صورت متن."""
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        dt = local(dt)
        j = jdatetime.datetime.fromgregorian(datetime=dt)
        return j.strftime("%Y/%m/%d %H:%M") if time else j.strftime("%Y/%m/%d")
    return jdatetime.date.fromgregorian(date=dt).strftime("%Y/%m/%d")


def event_label(name: str) -> str:
    if name.startswith(Event.VIEW):
        return "دیدن صفحه"
    if name.startswith(Event.DO):
        return "انجام عملیات"
    return EVENT_LABELS.get(name, name)


class Book:
    """نویسنده‌ی ساده‌ی xlsxwriter: برگه‌ی راست‌به‌چپ، سطر عنوان ثابت، فیلتر و عرض ستون."""

    def __init__(self, buf):
        self.wb = xlsxwriter.Workbook(buf, {"in_memory": True, "remove_timezone": True,
                                            "default_date_format": "yyyy-mm-dd hh:mm"})
        self.f_head = self.wb.add_format({"bold": True, "bg_color": "#0F5C59", "font_color": "#FFFFFF",
                                          "align": "center", "valign": "vcenter", "text_wrap": True, "border": 1})
        self.f_date = self.wb.add_format({"num_format": "yyyy-mm-dd hh:mm", "align": "center"})
        self.f_day = self.wb.add_format({"num_format": "yyyy-mm-dd", "align": "center"})
        self.f_num = self.wb.add_format({"num_format": "#,##0"})
        self.f_text = self.wb.add_format({"valign": "top"})
        self.f_wrap = self.wb.add_format({"text_wrap": True, "valign": "top"})
        self.f_title = self.wb.add_format({"bold": True, "font_size": 14, "font_color": "#0A4341"})
        self.f_key = self.wb.add_format({"bold": True, "bg_color": "#D3E5DF", "border": 1})
        self.f_val = self.wb.add_format({"border": 1, "num_format": "#,##0"})

    def sheet(self, title: str, headers: list[str], rows: Iterable[list], widths: list[int] | None = None) -> int:
        ws = self.wb.add_worksheet(title[:31])
        ws.right_to_left()
        ws.set_row(0, 30)
        for c, h in enumerate(headers):
            ws.write(0, c, h, self.f_head)
            ws.set_column(c, c, (widths or [])[c] if widths and c < len(widths) else 16)
        n = 0
        for n, row in enumerate(rows, start=1):  # noqa: B007
            if n > MAX_ROWS:
                ws.write(n, 0, f"… سقف {MAX_ROWS:,} سطر؛ بازه را کوتاه‌تر کنید.", self.f_text)
                n -= 1
                break
            for c, v in enumerate(row):
                if isinstance(v, datetime):
                    ws.write_datetime(n, c, v, self.f_date)
                elif isinstance(v, date):
                    ws.write_datetime(n, c, datetime(v.year, v.month, v.day), self.f_day)
                elif isinstance(v, bool):
                    ws.write(n, c, "بله" if v else "خیر")
                elif v is None:
                    ws.write_blank(n, c, None)
                else:
                    ws.write(n, c, v)
        ws.freeze_panes(1, 0)
        if n:
            ws.autofilter(0, 0, n, len(headers) - 1)
        return n

    def key_value(self, title: str, pairs: list[tuple[str, object]], note: str = "") -> None:
        ws = self.wb.add_worksheet(title[:31])
        ws.right_to_left()
        ws.set_column(0, 0, 46)
        ws.set_column(1, 1, 24)
        ws.write(0, 0, note or title, self.f_title)
        for r, (k, v) in enumerate(pairs, start=2):
            ws.write(r, 0, k, self.f_key)
            ws.write(r, 1, v, self.f_val)

    def text(self, title: str, lines: list[tuple[str, str]], head: tuple[str, str] = ("برگه", "توضیح")) -> None:
        ws = self.wb.add_worksheet(title[:31])
        ws.right_to_left()
        ws.set_column(0, 0, 28)
        ws.set_column(1, 1, 120)
        ws.write(0, 0, head[0], self.f_head)
        ws.write(0, 1, head[1], self.f_head)
        for r, (k, v) in enumerate(lines, start=1):
            ws.write(r, 0, k, self.f_key)
            ws.write(r, 1, v, self.f_wrap)

    def close(self) -> None:
        self.wb.close()


def _since(days: int):
    return timezone.now() - timedelta(days=days) if days else None


def _within(qs, field: str, since):
    return qs.filter(**{f"{field}__gte": since}) if since else qs


def _vid(visitor_id: str | None) -> str:
    return (visitor_id or "")[:8]


# ------------------------------------------------------------------ برگه‌ها
def _guide(book: Book, days: int) -> None:
    span = f"{days} روز اخیر" if days else "همه‌ی زمان‌ها"
    book.text("راهنما", [
        ("بازه‌ی گزارش", f"{span}. برگه‌های «کاربران» و «پایگاه‌ها» وضعیت کامل امروزند و بازه ندارند."),
        ("حریم خصوصی", "موبایل ناقص است (۰۹۱۲***۴۵۶۷)، متن پرسش و فرم، رمز و کلید در فایل نیست. بازدیدکننده با ۸ نویسه‌ی اول شناسه‌ی کوکی نشان داده می‌شود."),
        ("زمان‌ها", "ستون «زمان» به وقت تهران و قابل‌مرتب‌سازی است؛ ستون «تاریخ شمسی» همان زمان به شمسی است."),
        ("خلاصه", "شمارنده‌های کل سایت و بازه در یک نگاه."),
        ("قیف", "بازدیدکننده تا ساخت پایگاه، ورود داده و دیدن نقشه؛ هر بازدیدکننده در هر مرحله یک بار."),
        ("روزانه", "هر روز یک سطر: بازدیدکننده‌ی جدید، ثبت‌نام، ساخت پایگاه، ورود داده، نقشه، عملیات، درآمد."),
        ("منابع / صفحه فرود / ارجاع‌دهنده / دستگاه", "همان جدول‌های «گزارش منابع ورود» پنل، بدون سقف سطر."),
        ("بازدیدها", "هر نشست (۳۰ دقیقه بدون فعالیت = نشست جدید) با منبع، صفحه فرود و تعداد صفحه."),
        ("رویدادهای قیف", "درخواست کد، ورود، ثبت‌نام، ساخت پایگاه، ورود داده و دیدن نقشه."),
        ("ریزکارها", "هر دیدن صفحه (view:) و هر ارسال فرم (do:) کاربر واردشده با نام مسیر Django و شناسه‌های آدرس (پایگاه، جدول، نقشه …). ستون «موفق» برای فرم با خطا «خیر» است."),
        ("ثبت عملیات", "ActivityLog: ساخت، حذف، تمدید و تغییرهای تیم و نقش‌ها."),
        ("کاربران", "هر کاربر یک سطر با مسیر کامل: منبع اولین ورود، اولین پایگاه، اولین ورود داده، اولین نقشه، پرداخت، آخرین فعالیت و وضعیت فعال‌سازی."),
        ("پایگاه‌ها", "پایگاه‌های ساخته‌شده با پلن، حجم و وضعیت."),
        ("کارها", "ورود فایل، بکاپ، داده‌ی آماده‌ی ایران، پرسش فارسی … با وضعیت و مدت اجرا."),
        ("تحلیل‌ها", "ابزارهای تحلیل و پرسش‌های فارسی (بدون متن پرسش)."),
        ("نقشه‌ها / لایه‌ها / کلیدهای API", "انتشار و اشتراک؛ هش کلیدها نیست."),
        ("فاکتورها / پشتیبانی", "فروش و تیکت‌ها (بدون متن)."),
        ("کلاس‌ها / برداشت / دستیار / دانش", "استفاده از کلاس، برداشت میدانی، دستیار هوشمند، جست‌وجوهای بی‌نتیجه و بازخورد مقاله‌ها."),
        ("لینک‌ها", "لینک‌های ردیابی‌شده‌ی /go/ با تعداد کلیک."),
    ])


def _summary(book: Book, days: int, since) -> None:
    from accounts.models import User
    from billing.models import Invoice
    from databases.models import UserDatabase
    from jobs.models import Job

    vis = _within(Visitor.objects.all(), "first_seen", since)
    ev = _within(Event.objects.all(), "created_at", since)
    paid = _within(Invoice.objects.filter(status=Invoice.Status.PAID), "paid_at", since)
    book.key_value("خلاصه", [
        ("تاریخ تهیه‌ی گزارش", jalali(timezone.now())),
        ("بازه", f"{days} روز اخیر" if days else "همه‌ی زمان‌ها"),
        ("بازدیدکننده‌ی جدید", vis.count()),
        ("نشست (Visit)", _within(Visit.objects.all(), "started_at", since).count()),
        ("درخواست کد ورود", ev.filter(name=Event.OTP_REQUESTED).count()),
        ("ثبت‌نام جدید", ev.filter(name=Event.SIGNUP).count()),
        ("ورود (کاربر قبلی)", ev.filter(name=Event.LOGIN).count()),
        ("ساخت پایگاه (رویداد)", ev.filter(name=Event.DB_CREATED).count()),
        ("ورود داده (در صف)", ev.filter(name=Event.IMPORT_QUEUED).count()),
        ("دیدن نقشه جدول", ev.filter(name=Event.MAP_VIEWED).count()),
        ("دیدن صفحه (کاربر واردشده)", ev.filter(name__startswith=Event.VIEW).count()),
        ("عملیات و ارسال فرم", ev.filter(name__startswith=Event.DO).count()),
        ("فاکتور پرداخت‌شده", paid.count()),
        ("درآمد (تومان)", paid.aggregate(s=Sum("amount_toman"))["s"] or 0),
        ("کارهای ناموفق", _within(Job.objects.filter(status=Job.Status.FAILED), "created_at", since).count()),
        ("— وضعیت امروز —", ""),
        ("کاربران سایت", User.objects.filter(is_staff=False).count()),
        ("پایگاه فعال", UserDatabase.objects.filter(status=UserDatabase.Status.ACTIVE).count()),
        ("حجم کل داده‌ی مشتریان (مگابایت)", round((UserDatabase.objects.aggregate(s=Sum("size_bytes"))["s"] or 0) / 1048576)),
    ], note="خلاصه‌ی سایت")


def _funnel(book: Book, days: int) -> None:
    rows = [[s["label"], s["n"], s["of_total"], s["of_prev"]] for s in reports.funnel(days or 36500)]
    book.sheet("قیف", ["مرحله", "تعداد بازدیدکننده", "درصد از کل", "درصد از مرحله‌ی قبل"], rows, [28, 18, 14, 18])


def _breakdown(book: Book, days: int) -> None:
    head = ["بازدیدکننده", "کد خواستند", "ثبت‌نام", "نرخ ثبت‌نام", "ساخت پایگاه", "کد گرفتند و وارد نکردند", "خطای پیامک"]

    def rows(fields, limit=5000):
        return [[*r["keys"], r["visitors"], r["requested"], r["signup"], r["signup_rate"], r["dbs"], r["stuck"],
                 r["send_failed"]] for r in reports.breakdown(fields, days or 36500, limit)]

    book.sheet("منابع", ["منبع", "نوع", "کمپین", *head], rows(["first_source", "first_medium", "first_campaign"]),
               [22, 14, 24, 12, 12, 10, 12, 12, 18, 12])
    book.sheet("صفحه فرود", ["صفحه فرود", *head], rows(["first_landing"]), [44, 12, 12, 10, 12, 12, 18, 12])
    book.sheet("ارجاع‌دهنده", ["دامنه", *head], rows(["first_referrer"]), [30, 12, 12, 10, 12, 12, 18, 12])
    book.sheet("دستگاه", ["دستگاه", *head], rows(["device"]), [16, 12, 12, 10, 12, 12, 18, 12])


def _daily(book: Book, since) -> None:
    from billing.models import Invoice
    from support.models import Ticket

    tz = timezone.get_current_timezone()
    table: dict[date, dict[str, int]] = {}

    def add(qs, field, key, **agg):
        q = qs.annotate(d=TruncDate(field, tzinfo=tz)).values("d")
        for r in q.annotate(n=Count("id") if not agg else Sum(agg["sum"])):
            table.setdefault(r["d"], {}).update({key: r["n"] or 0})

    add(_within(Visitor.objects.all(), "first_seen", since), "first_seen", "visitors")
    add(_within(Visit.objects.all(), "started_at", since), "started_at", "visits")
    ev = _within(Event.objects.all(), "created_at", since)
    for name, key in [(Event.OTP_REQUESTED, "otp"), (Event.SIGNUP, "signup"), (Event.LOGIN, "login"),
                      (Event.DB_CREATED, "db"), (Event.IMPORT_QUEUED, "imp"), (Event.MAP_VIEWED, "map")]:
        add(ev.filter(name=name), "created_at", key)
    add(ev.filter(name__startswith=Event.VIEW), "created_at", "views")
    add(ev.filter(name__startswith=Event.DO), "created_at", "dos")
    paid = _within(Invoice.objects.filter(status=Invoice.Status.PAID), "paid_at", since)
    add(paid, "paid_at", "paid")
    add(paid, "paid_at", "revenue", sum="amount_toman")
    add(_within(Ticket.objects.all(), "created_at", since), "created_at", "tickets")
    keys = ["visitors", "visits", "otp", "signup", "login", "db", "imp", "map", "views", "dos", "paid", "revenue", "tickets"]
    rows = [[d, jalali(d), *[table[d].get(k, 0) for k in keys]] for d in sorted(x for x in table if x)]
    book.sheet("روزانه", ["تاریخ", "تاریخ شمسی", "بازدیدکننده‌ی جدید", "نشست", "درخواست کد", "ثبت‌نام", "ورود",
                          "ساخت پایگاه", "ورود داده", "دیدن نقشه", "دیدن صفحه", "عملیات", "فاکتور پرداخت‌شده",
                          "درآمد (تومان)", "تیکت"], rows, [12, 12] + [12] * 13)


def _visits(book: Book, since) -> None:
    qs = _within(Visit.objects.select_related("visitor"), "started_at", since).order_by("-started_at")
    rows = ([local(v.started_at), jalali(v.started_at), _vid(v.visitor.vid), v.visitor.user_id, v.source, v.medium,
             v.campaign, v.content, v.referrer_host, v.landing_path, v.last_path, v.pages, v.device, v.browser,
             v.in_app] for v in qs.iterator(chunk_size=2000))
    book.sheet("بازدیدها", ["زمان", "تاریخ شمسی", "بازدیدکننده", "شناسه‌ی کاربر", "منبع", "نوع", "کمپین", "محتوا",
                            "ارجاع‌دهنده", "صفحه فرود", "آخرین صفحه", "صفحه‌ها", "دستگاه", "مرورگر", "مرورگر برنامه"],
               rows, [17, 17, 12, 10, 14, 10, 20, 14, 20, 30, 30, 8, 10, 10, 12])


def _events(book: Book, since) -> None:
    qs = (_within(Event.objects.select_related("visitor"), "created_at", since)
          .exclude(Q(name__startswith=Event.VIEW) | Q(name__startswith=Event.DO)).order_by("-created_at"))
    rows = ([local(e.created_at), jalali(e.created_at), event_label(e.name), e.name, _vid(e.visitor.vid),
             e.visitor.user_id, e.visitor.first_source, e.visitor.first_campaign, e.path,
             "; ".join(f"{k}={v}" for k, v in (e.meta or {}).items())] for e in qs.iterator(chunk_size=2000))
    book.sheet("رویدادهای قیف", ["زمان", "تاریخ شمسی", "رویداد", "نام فنی", "بازدیدکننده", "شناسه‌ی کاربر",
                                 "منبع اولیه", "کمپین اولیه", "مسیر", "جزئیات"], rows, [17, 17, 22, 18, 12, 10, 14, 18, 34, 40])


def _actions(book: Book, since) -> None:
    qs = (_within(Event.objects.select_related("visitor"), "created_at", since)
          .filter(Q(name__startswith=Event.VIEW) | Q(name__startswith=Event.DO)).order_by("-created_at"))

    def row(e):
        m = e.meta or {}
        extra = "; ".join(f"{k}={v}" for k, v in m.items() if k not in ("route", "status", "ok"))
        return [local(e.created_at), jalali(e.created_at), event_label(e.name), m.get("route", e.name), e.path,
                m.get("status"), bool(m.get("ok", True)), extra, e.visitor.user_id, _vid(e.visitor.vid)]

    book.sheet("ریزکارها", ["زمان", "تاریخ شمسی", "نوع", "مسیر (route)", "آدرس", "کد پاسخ", "موفق", "شناسه‌های آدرس",
                            "شناسه‌ی کاربر", "بازدیدکننده"], (row(e) for e in qs.iterator(chunk_size=2000)),
               [17, 17, 14, 34, 40, 8, 8, 36, 10, 12])


def _activity(book: Book, since) -> None:
    from databases.models import ActivityLog

    qs = _within(ActivityLog.objects.all(), "created_at", since).order_by("-created_at")
    rows = ([local(a.created_at), jalali(a.created_at), a.action, a.user_id, a.database_id, a.success,
             mask_phone(a.message)] for a in qs.iterator(chunk_size=2000))
    book.sheet("ثبت عملیات", ["زمان", "تاریخ شمسی", "عملیات", "شناسه‌ی کاربر", "شناسه‌ی پایگاه", "موفق", "شرح"],
               rows, [17, 17, 20, 10, 10, 8, 70])


def _users(book: Book) -> None:
    from accounts.models import User
    from billing.models import Invoice
    from databases.models import UserDatabase
    from jobs.models import Job

    def per_user(qs, key):
        return {r[key]: r for r in qs.values(key).annotate(n=Count("id"), first=Min("created_at"), last=Max("created_at"))
                if r[key] is not None}

    dbs = per_user(UserDatabase.objects.filter(owner__isnull=False), "owner_id")
    imports = per_user(Job.objects.filter(kind__in=[Job.Kind.IMPORT, Job.Kind.OSM_IMPORT], status=Job.Status.DONE),
                       "user_id")
    tools = per_user(Job.objects.filter(kind__in=[Job.Kind.TOOL, Job.Kind.ASK]), "user_id")
    paid = {r["user_id"]: r for r in Invoice.objects.filter(status=Invoice.Status.PAID).values("user_id")
            .annotate(n=Count("id"), s=Sum("amount_toman"), last=Max("paid_at"))}
    ev = {}
    for r in (Event.objects.filter(visitor__user__isnull=False)
              .values("visitor__user_id")
              .annotate(views=Count("id", filter=Q(name__startswith=Event.VIEW)),
                        dos=Count("id", filter=Q(name__startswith=Event.DO)),
                        map_first=Min("created_at", filter=Q(name=Event.MAP_VIEWED)),
                        last=Max("created_at"))):
        ev[r["visitor__user_id"]] = r
    first_visitor = {}
    for v in Visitor.objects.filter(user__isnull=False).order_by("-first_seen"):
        first_visitor[v.user_id] = v  # قدیمی‌ترین آخر می‌نشیند

    def rows():
        for u in User.objects.filter(is_staff=False).order_by("-date_joined").iterator(chunk_size=2000):
            v, d, i = first_visitor.get(u.pk), dbs.get(u.pk), imports.get(u.pk)
            e, p, t = ev.get(u.pk, {}), paid.get(u.pk), tools.get(u.pk)
            stage = ("پرداخت‌کننده" if p else "فعال‌شده" if (i and e.get("map_first")) else "داده وارد کرده" if i
                     else "پایگاه ساخته" if d else "فقط ثبت‌نام")
            yield [u.pk, mask_phone(u.phone), u.organization, local(u.date_joined), jalali(u.date_joined),
                   v.first_source if v else "", v.first_medium if v else "", v.first_campaign if v else "",
                   v.first_landing if v else "", v.device if v else "", v.in_app if v else "",
                   d["n"] if d else 0, local(d["first"]) if d else None, local(i["first"]) if i else None,
                   i["n"] if i else 0, local(e.get("map_first")), t["n"] if t else 0, e.get("views", 0),
                   e.get("dos", 0), p["n"] if p else 0, p["s"] if p else 0, local(u.last_login),
                   local(max([x for x in (e.get("last"), u.last_login) if x], default=None)), stage]

    book.sheet("کاربران", ["شناسه", "موبایل", "سازمان", "زمان ثبت‌نام", "تاریخ شمسی", "منبع اولیه", "نوع منبع",
                           "کمپین", "صفحه فرود", "دستگاه", "مرورگر برنامه", "پایگاه‌ها", "اولین پایگاه",
                           "اولین ورود داده", "ورود موفق داده", "اولین نقشه", "تحلیل/پرسش", "صفحه‌ی دیده‌شده",
                           "عملیات", "فاکتور پرداخت‌شده", "پرداخت (تومان)", "آخرین ورود", "آخرین فعالیت", "مرحله"],
               rows(), [8, 14, 22, 17, 12, 14, 10, 18, 26, 10, 12, 8, 17, 17, 9, 17, 9, 10, 9, 10, 12, 17, 17, 16])


def _databases(book: Book) -> None:
    from databases.models import UserDatabase

    qs = UserDatabase.objects.select_related("plan", "server").order_by("-created_at")
    rows = ([d.pk, d.owner_id, d.plan.slug if d.plan else "", d.get_status_display(), local(d.created_at),
             jalali(d.created_at), local(d.expires_at), round(d.size_bytes / 1048576, 1), d.plan.quota_mb if d.plan else "",
             d.extensions.count(), d.last_error[:120]] for d in qs.iterator(chunk_size=500))
    book.sheet("پایگاه‌ها", ["شناسه", "شناسه‌ی مالک", "پلن", "وضعیت", "ساخت", "تاریخ شمسی", "انقضا", "حجم (MB)",
                             "سقف (MB)", "افزونه‌ها", "آخرین خطا"], rows, [8, 10, 14, 16, 17, 12, 17, 10, 10, 8, 40])


def _jobs(book: Book, since) -> None:
    from jobs.models import Job

    qs = _within(Job.objects.all(), "created_at", since).order_by("-created_at")

    def row(j):
        secs = (j.finished_at - j.started_at).total_seconds() if j.started_at and j.finished_at else None
        return [local(j.created_at), jalali(j.created_at), j.get_kind_display(), j.get_status_display(),
                j.get_trigger_display(), j.user_id, j.database_id, round(j.size_bytes / 1048576, 1) if j.size_bytes else 0,
                round(secs) if secs is not None else None, (j.message or "")[:200]]

    book.sheet("کارها", ["زمان", "تاریخ شمسی", "نوع", "وضعیت", "شروع‌کننده", "شناسه‌ی کاربر", "شناسه‌ی پایگاه",
                         "حجم (MB)", "مدت (ثانیه)", "پیام"], (row(j) for j in qs.iterator(chunk_size=2000)),
               [17, 12, 22, 16, 10, 10, 10, 10, 10, 60])


def _analysis(book: Book, since) -> None:
    from analysis.models import Question, ToolRun

    def rows():
        for t in _within(ToolRun.objects.all(), "created_at", since).order_by("-created_at").iterator(chunk_size=2000):
            yield [local(t.created_at), jalali(t.created_at), "ابزار تحلیل", t.tool, t.user_id, t.database_id,
                   t.rows, (t.summary or "")[:160]]
        for q in _within(Question.objects.all(), "created_at", since).order_by("-created_at").iterator(chunk_size=2000):
            yield [local(q.created_at), jalali(q.created_at), "پرسش فارسی", q.result_kind or q.goal or "", q.user_id,
                   q.database_id, q.rows, f"تلاش={q.attempts}"]

    book.sheet("تحلیل‌ها", ["زمان", "تاریخ شمسی", "نوع", "ابزار / نتیجه", "شناسه‌ی کاربر", "شناسه‌ی پایگاه", "سطر",
                            "خلاصه"], rows(), [17, 12, 14, 24, 10, 10, 10, 60])


def _maps(book: Book, since) -> None:
    from maps.models import WebMap
    from publish.models import ApiKey, Layer

    qs = _within(WebMap.objects.annotate(nl=Count("layers")), "created_at", since).order_by("-created_at")
    book.sheet("نقشه‌ها", ["زمان", "تاریخ شمسی", "شناسه", "شناسه‌ی پایگاه", "عمومی", "لایه‌ها", "نقشه‌ی پایه"],
               ([local(m.created_at), jalali(m.created_at), m.pk, m.database_id, m.is_public, m.nl, m.basemap]
                for m in qs.iterator(chunk_size=1000)), [17, 12, 8, 10, 8, 8, 14])
    ql = _within(Layer.objects.select_related("service"), "created_at", since).order_by("-created_at")
    book.sheet("لایه‌های منتشرشده", ["زمان", "تاریخ شمسی", "شناسه‌ی پایگاه", "جدول", "نوع هندسه", "SRID", "عمومی"],
               ([local(x.created_at), jalali(x.created_at), x.service.database_id, f"{x.schema}.{x.table}", x.geom_type,
                 x.srid, x.is_public] for x in ql.iterator(chunk_size=1000)), [17, 12, 10, 30, 14, 8, 8])
    qk = _within(ApiKey.objects.all(), "created_at", since).order_by("-created_at")
    book.sheet("کلیدهای API", ["زمان", "تاریخ شمسی", "شناسه‌ی پایگاه", "نام", "قابلیت نوشتن", "آخرین استفاده", "باطل‌شده"],
               ([local(k.created_at), jalali(k.created_at), k.database_id, k.name, k.can_write, local(k.last_used_at),
                 local(k.revoked_at)] for k in qk.iterator(chunk_size=1000)), [17, 12, 10, 22, 10, 17, 17])


def _money(book: Book, since) -> None:
    from billing.models import Invoice
    from support.models import Ticket

    qs = _within(Invoice.objects.select_related("plan"), "created_at", since).order_by("-created_at")
    book.sheet("فاکتورها", ["زمان", "تاریخ شمسی", "شماره", "شناسه‌ی کاربر", "نوع", "پلن", "مبلغ (تومان)", "روش",
                            "درگاه", "وضعیت", "زمان پرداخت"],
               ([local(i.created_at), jalali(i.created_at), i.number, i.user_id, i.get_kind_display(), i.plan.slug,
                 i.amount_toman, i.get_method_display() if i.method else "", i.gateway, i.get_status_display(),
                 local(i.paid_at)] for i in qs.iterator(chunk_size=1000)), [17, 12, 14, 10, 16, 14, 12, 18, 12, 16, 17])
    qt = _within(Ticket.objects.all(), "created_at", since).order_by("-created_at")
    book.sheet("پشتیبانی", ["زمان", "تاریخ شمسی", "شماره", "شناسه‌ی کاربر", "دسته", "وضعیت", "بسته‌شده"],
               ([local(t.created_at), jalali(t.created_at), t.number, t.user_id, t.get_category_display(),
                 t.get_status_display(), local(t.closed_at)] for t in qt.iterator(chunk_size=1000)),
               [17, 12, 12, 10, 12, 16, 17])


def _education(book: Book, since) -> None:
    from classroom.models import Classroom
    from survey.models import SurveyProject

    qs = _within(Classroom.objects.annotate(n=Count("enrollments")), "created_at", since).order_by("-created_at")
    book.sheet("کلاس‌ها", ["زمان", "تاریخ شمسی", "شناسه", "شناسه‌ی استاد", "ظرفیت", "ثبت‌نام‌شده", "وضعیت", "باز"],
               ([local(c.created_at), jalali(c.created_at), c.pk, c.teacher_id, c.capacity, c.n, c.get_status_display(),
                 c.is_open] for c in qs.iterator(chunk_size=500)), [17, 12, 8, 10, 8, 10, 14, 8])
    qp = _within(SurveyProject.objects.all(), "created_at", since).order_by("-created_at")
    book.sheet("برداشت", ["زمان", "تاریخ شمسی", "شناسه", "شناسه‌ی پایگاه", "SRID", "قالب", "بایگانی"],
               ([local(p.created_at), jalali(p.created_at), p.pk, p.database_id, p.srid, p.template,
                 local(p.archived_at)] for p in qp.iterator(chunk_size=500)), [17, 12, 8, 10, 8, 14, 17])


def _assistant_kb(book: Book, since) -> None:
    from assistant.models import Usage
    from kb.models import Feedback, MissedQuery

    qs = _within(Usage.objects.all(), "created_at", since).order_by("-created_at")
    book.sheet("دستیار", ["زمان", "تاریخ شمسی", "شناسه‌ی کاربر", "بازیگر", "وضعیت", "حالت", "صفحه", "طول پاسخ",
                          "تأخیر (ms)", "مفید"],
               ([local(u.created_at), jalali(u.created_at), u.user_id, u.actor, u.status, u.mode, u.path, u.answer_chars,
                 u.latency_ms, "" if u.helpful is None else u.helpful] for u in qs.iterator(chunk_size=2000)),
               [17, 12, 10, 10, 12, 10, 30, 10, 10, 8])
    book.sheet("جست‌وجوی بی‌نتیجه", ["عبارت", "تعداد", "آخرین بار", "حل‌شده"],
               ([m.sample[:120], m.count, local(m.last_seen), m.resolved]
                for m in MissedQuery.objects.order_by("-count")[:2000]), [50, 8, 17, 8])
    qf = _within(Feedback.objects.select_related("article"), "created_at", since).order_by("-created_at")
    book.sheet("بازخورد مقاله", ["زمان", "تاریخ شمسی", "مقاله", "مفید", "نظر"],
               ([local(f.created_at), jalali(f.created_at), f.article.slug, f.helpful, (f.comment or "")[:300]]
                for f in qf.iterator(chunk_size=1000)), [17, 12, 30, 8, 60])


def _links(book: Book) -> None:
    book.sheet("لینک‌ها", ["نام کوتاه", "نام", "مقصد", "منبع", "نوع", "کمپین", "کلیک", "آخرین کلیک", "فعال", "ساخت"],
               ([x.slug, x.name, x.destination, x.utm_source, x.utm_medium, x.utm_campaign, x.clicks,
                 local(x.last_click_at), x.is_active, local(x.created_at)] for x in TrackedLink.objects.order_by("-clicks")),
               [22, 22, 30, 14, 10, 20, 8, 17, 8, 17])


def build(days: int = 90) -> bytes:
    """فایل xlsx کامل را در حافظه می‌سازد. days=۰ یعنی همه‌ی زمان‌ها."""
    since = _since(days)
    buf = io.BytesIO()
    book = Book(buf)
    _guide(book, days)
    _summary(book, days, since)
    _funnel(book, days)
    _daily(book, since)
    _breakdown(book, days)
    _users(book)
    _actions(book, since)
    _events(book, since)
    _visits(book, since)
    _activity(book, since)
    _databases(book)
    _jobs(book, since)
    _analysis(book, since)
    _maps(book, since)
    _money(book, since)
    _education(book, since)
    _assistant_kb(book, since)
    _links(book)
    book.close()
    return buf.getvalue()
