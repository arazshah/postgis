"""ثبت تیکت، پاسخ و اطلاع‌رسانی."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from core.models import SiteSettings

from .models import Ticket, TicketMessage

log = logging.getLogger(__name__)

MAX_OPEN_TICKETS = 5
MAX_NEW_PER_DAY = 10


class SupportError(Exception):
    pass


def can_open(user) -> str | None:
    if Ticket.objects.filter(user=user).exclude(status=Ticket.Status.CLOSED).count() >= MAX_OPEN_TICKETS:
        return f"شما {MAX_OPEN_TICKETS} تیکت باز دارید. لطفاً در همان تیکت‌ها ادامه دهید یا یکی را ببندید."
    if Ticket.objects.filter(user=user, created_at__gte=timezone.now() - timedelta(days=1)).count() >= MAX_NEW_PER_DAY:
        return "تعداد تیکت‌های امروز شما زیاد بوده است. فردا دوباره تلاش کنید."
    return None


def open_ticket(user, *, subject, category, body, database=None, plan=None, attachment=None) -> Ticket:
    reason = can_open(user)
    if reason:
        raise SupportError(reason)
    t = Ticket.objects.create(user=user, subject=subject.strip(), category=category, database=database, plan=plan)
    TicketMessage.objects.create(ticket=t, author=user, body=body.strip(), attachment=attachment or "")
    _notify_staff(t, "تیکت جدید")
    return t


def user_reply(ticket: Ticket, user, body: str, attachment=None) -> TicketMessage:
    if ticket.is_closed:
        raise SupportError("این تیکت بسته شده است؛ برای ادامه، تیکت جدید ثبت کنید.")
    m = TicketMessage.objects.create(ticket=ticket, author=user, body=body.strip(), attachment=attachment or "")
    ticket.status = Ticket.Status.OPEN
    ticket.updated_at = timezone.now()
    ticket.save(update_fields=["status", "updated_at"])
    _notify_staff(ticket, "پاسخ جدید کاربر")
    return m


def staff_reply(ticket: Ticket, staff, body: str, attachment=None, close: bool = False) -> TicketMessage:
    m = TicketMessage.objects.create(ticket=ticket, author=staff, is_staff=True, body=body.strip(),
                                     attachment=attachment or "")
    now = timezone.now()
    ticket.status = Ticket.Status.CLOSED if close else Ticket.Status.ANSWERED
    ticket.updated_at = now
    ticket.closed_at = now if close else None
    ticket.save(update_fields=["status", "updated_at", "closed_at"])
    from databases.services import _notify

    _notify(ticket.user, f"پاسخ تیکت {ticket.number}",
            f"به تیکت {ticket.number} («{ticket.subject[:40]}») پاسخ داده شد. برای دیدن پاسخ وارد حساب خود شوید.")
    return m


def close(ticket: Ticket):
    if ticket.is_closed:
        return
    ticket.status = Ticket.Status.CLOSED
    ticket.closed_at = ticket.updated_at = timezone.now()
    ticket.save(update_fields=["status", "closed_at", "updated_at"])


def _notify_staff(ticket: Ticket, what: str):
    """پیامک به تلفن پشتیبانی (اگر در تنظیمات سایت موبایل باشد) و ایمیل به ایمیل پشتیبانی."""
    from django.core.mail import send_mail

    from accounts.models import normalize_mobile
    from accounts.sms import send_text

    conf = SiteSettings.get()
    text = f"{what} {ticket.number}: {ticket.subject[:60]}"
    try:
        phone = normalize_mobile(conf.support_phone or "")
    except Exception:  # noqa: BLE001
        phone = ""
    if phone:
        try:
            send_text(phone, f"{conf.site_name}: {text}")
        except Exception:  # noqa: BLE001
            log.exception("staff sms failed")
    if conf.support_email:
        send_mail(f"[{conf.site_name}] {text}", text, None, [conf.support_email], fail_silently=True)
