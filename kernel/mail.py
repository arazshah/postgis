"""ایمیل سکو: تنظیم SMTP در پنل، صف با تلاش دوباره، قالب‌های ثبت‌پذیر و سیاست رضایت (ADR-0009).

- هر پلاگین قالب خودش را با `register(...)` ثبت می‌کند و با `send(...)` می‌فرستد؛ هسته هیچ پلاگینی را نمی‌شناسد.
- دسته‌ها: `security` (تأیید/بازنشانی؛ همیشه می‌رود)، `service` (هشدار و رسید)، `product` (خبر محصول)، `marketing`
  (فقط با رضایت از `set_consent_provider`). جز `security`، فقط به **ایمیل تأییدشده** می‌رود.
- درخواست کاربر منتظر SMTP نمی‌ماند: ایمیل در صف ثبت می‌شود؛ `urgent=True` بعد از commit یک بار فوری امتحان می‌کند و
  اگر نشد کار دوره‌ای (`tick`) با تأخیر افزایشی دوباره می‌فرستد. هیچ‌وقت استثنا به فراخوان نمی‌دهد.
- بدون تنظیم فعال در پنل، همان `EMAIL_BACKEND` پروژه (کنسول/متغیر محیطی/آزمون) استفاده می‌شود.
- رمز SMTP هرگز در لاگ/خطا نمی‌آید.
"""
from __future__ import annotations

import datetime
import html as htmllib
import logging
import re
import smtplib
import ssl
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.mail.backends.smtp import EmailBackend
from django.db import transaction
from django.template import Context, Template
from django.template.loader import render_to_string
from django.utils import timezone

from . import crypto
from .plugins import registry

log = logging.getLogger(__name__)

POINT = "mail.template"
SECURITY, SERVICE, PRODUCT, MARKETING = "security", "service", "product", "marketing"
CATEGORIES = {SECURITY: "امنیتی", SERVICE: "هشدار و رسید", PRODUCT: "خبر محصول", MARKETING: "پیشنهاد و بازاریابی"}
RESERVE, MAX_ATTEMPTS, BACKOFF_MIN, TIMEOUT, BATCH, KEEP_DAYS, DEDUPE_HOURS = 20, 4, (5, 30, 180), 15, 25, 90, 24


class MailError(Exception):
    pass


@dataclass(frozen=True)
class MailTemplate:
    key: str
    plugin: str
    category: str
    subject: str  # قالب جنگو؛ مثلاً «تأیید ایمیل {{ SITE_NAME }}»
    template: str  # مسیر قالب HTML بدنه (extends mail/_base.html)


def register(key: str, *, plugin: str, category: str, subject: str, template: str) -> MailTemplate:
    if category not in CATEGORIES:
        raise ValueError(f"دسته‌ی ایمیل ناشناخته است: {category}")
    t = MailTemplate(key, plugin, category, subject, template)
    registry.add(POINT, key, t, plugin=plugin)
    return t


def get(key: str) -> MailTemplate | None:
    return registry.get(POINT, key)


def templates() -> list[MailTemplate]:
    return registry.values(POINT)


# ---------------------------------------------------------------- رضایت (بازاریابی)
_consent = None


def set_consent_provider(func) -> None:
    """func(user) -> bool: کاربر ایمیل بازاریابی می‌خواهد؟ بدون ثبت، بازاریابی هرگز نمی‌رود."""
    global _consent
    _consent = func


def _wants_marketing(user) -> bool:
    try:
        return bool(user is not None and _consent is not None and _consent(user))
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- تنظیم
def config():
    from .models import MailConfig

    return MailConfig.objects.first()


def _ready(cfg) -> bool:
    return bool(cfg and cfg.enabled and cfg.host and cfg.password_enc)


def save_config(*, enabled: bool, host: str, port: int, security: str, username: str, password: str = "",
                from_name: str = "", from_email: str = "", reply_to: str = "", daily_limit: int = 200):
    from .models import MailConfig

    cfg = config() or MailConfig()
    cfg.host, cfg.port, cfg.security = host.strip(), port, security
    cfg.username, cfg.from_name, cfg.from_email = username.strip(), from_name.strip(), from_email.strip()
    cfg.reply_to, cfg.daily_limit = reply_to.strip(), max(1, int(daily_limit))
    if password.strip():
        cfg.password_enc, cfg.password_hint = crypto.encrypt(password.strip()), "•" * 4
    cfg.enabled = bool(enabled and cfg.host and cfg.password_enc)
    cfg.save()
    return cfg


def _smtp_backend(cfg) -> EmailBackend:
    return EmailBackend(
        host=cfg.host, port=cfg.port, username=cfg.username, password=crypto.decrypt(cfg.password_enc),
        use_tls=cfg.security == "starttls", use_ssl=cfg.security == "ssl", timeout=TIMEOUT,
        fail_silently=False)


def _connection():
    """اتصال ارسال؛ جداشده تا آزمون mock کند. تنظیم پنل مقدم است، وگرنه backend پروژه."""
    cfg = config()
    return _smtp_backend(cfg) if _ready(cfg) else get_connection()


def _safe_error(exc: Exception) -> str:
    """متن خطا بدون رمز و جزئیات داخلی؛ فارسی و کوتاه."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "ورود به سرور ایمیل ردشد؛ نام کاربری یا رمز را بررسی کنید."
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "نشانی گیرنده پذیرفته نشد."
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "نشانی فرستنده پذیرفته نشد."
    if isinstance(exc, (ssl.SSLError, ssl.CertificateError)):
        return "برقراری اتصال امن ممکن نشد؛ پورت و نوع امنیت را بررسی کنید."
    if isinstance(exc, (smtplib.SMTPException, OSError)):
        return "اتصال به سرور ایمیل برقرار نشد."
    return "ارسال ایمیل ناموفق بود."


def test_connection() -> tuple[bool, str]:
    cfg = config()
    if not _ready(cfg):
        return False, "ارسال ایمیل فعال نیست یا رمز تنظیم نشده است."
    conn = _smtp_backend(cfg)
    try:
        conn.open()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        msg = _safe_error(exc)
        cfg.last_error = msg
        cfg.save(update_fields=["last_error"])
        return False, msg
    cfg.last_ok, cfg.last_error = timezone.now(), ""
    cfg.save(update_fields=["last_ok", "last_error"])
    return True, "اتصال و ورود به سرور ایمیل موفق بود."


# ---------------------------------------------------------------- ساخت پیام
def _site_name() -> str:
    try:  # نام سایت را مدیر در پنل می‌دهد؛ هسته core را import نمی‌کند، پس دیر و با نام مدل
        from django.apps import apps

        return apps.get_model("core", "SiteSettings").get().site_name or "postgis.ir"
    except Exception:  # noqa: BLE001
        return getattr(settings, "SITE_NAME", "") or "postgis.ir"


def base_url() -> str:
    return (getattr(settings, "CANONICAL_URL", "") or "").rstrip("/")


def to_text(html: str) -> str:
    """نسخه‌ی متنی از HTML: پیوندها به شکل «متن (نشانی)»؛ برای کلاینت‌های ساده و ضد اسپم."""
    html = re.sub(r"(?is)<(style|head|script).*?</\1>", "", html)
    html = re.sub(r'(?is)<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                  lambda m: f"{re.sub('<[^>]+>', '', m.group(2)).strip()} ({m.group(1)})", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</tr>|</li>", "\n", html)
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", html))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.strip() for line in text.splitlines())).strip()


def render(template_key: str, context: dict | None = None) -> tuple[str, str, str]:
    t = get(template_key)
    if t is None:
        raise MailError(f"قالب ایمیل ثبت نشده است: {template_key}")
    ctx = {"SITE_NAME": _site_name(), "BASE_URL": base_url(), **(context or {})}
    subject = " ".join(Template(t.subject).render(Context(ctx, autoescape=False)).split())[:200]
    html = render_to_string(t.template, {**ctx, "subject": subject, "category": t.category})
    return subject, html, to_text(html)


def _pref(user):
    from .models import NotifyPref

    return NotifyPref.objects.filter(user=user).first() if getattr(user, "pk", None) else None


def _pref_allows(user, category: str) -> bool:
    pref = _pref(user)
    if pref is None:
        return True
    return pref.email_service if category == SERVICE else pref.email_product


def available() -> bool:
    """سرور ایمیل واقعاً تنظیم است؟ (تنظیم پنل یا EMAIL_HOST). وگرنه اعلان‌ها به پیامک برمی‌گردند و گم نمی‌شوند."""
    return _ready(config()) or bool(getattr(settings, "EMAIL_HOST", ""))


def can_email(user) -> bool:
    """اعلان سرویس را می‌شود با ایمیل رساند؟ (ایمیل تأییدشده + سرور تنظیم + کاربر خاموشش نکرده)."""
    return bool(user is not None and getattr(user, "email", None) and getattr(user, "email_verified_at", None)
                and getattr(user, "is_active", True) and available() and _pref_allows(user, SERVICE))


def _eligible(user, to: str, category: str) -> str:
    """"" = مجاز؛ وگرنه دلیل رد."""
    if not to:
        return "no-address"
    if category == SECURITY:
        return ""
    if user is not None:
        if getattr(user, "email", None) and user.email.lower() == to.lower() and not getattr(user, "email_verified_at", None):
            return "unverified"
        if not getattr(user, "is_active", True):
            return "inactive"
    if category == MARKETING and not _wants_marketing(user):
        return "no-consent"
    if user is not None and category in (SERVICE, PRODUCT) and not _pref_allows(user, category):
        return "pref-off"
    return ""


def send(template_key: str, *, user=None, to: str = "", context: dict | None = None, key: str = "",
         urgent: bool = False, headers: dict | None = None):
    """ایمیل را در صف می‌گذارد. برمی‌گرداند OutgoingEmail (وضعیت queued یا skipped) یا None؛ هرگز استثنا نمی‌دهد.

    `to` خالی = ایمیل خود کاربر. `key` = تکرارگیری (همان کلید به همان گیرنده در ۲۴ ساعت دوباره ساخته نمی‌شود).
    """
    from .models import OutgoingEmail

    try:
        t = get(template_key)
        if t is None:
            log.error("mail template missing: %s", template_key)
            return None
        to = (to or (getattr(user, "email", "") or "")).strip().lower()
        why = _eligible(user, to, t.category)
        subject, html, text = render(template_key, context)
        hdrs = dict(headers or {})
        if t.category == MARKETING:
            hdrs.setdefault("Precedence", "bulk")
        else:
            hdrs.setdefault("Auto-Submitted", "auto-generated")
        if why:
            return OutgoingEmail.objects.create(user=user if getattr(user, "pk", None) else None, to=to or "-",
                                                template=template_key, category=t.category, subject=subject,
                                                status=OutgoingEmail.Status.SKIPPED, error=why, key=key[:120])
        if key and OutgoingEmail.objects.filter(
                to=to, key=key, created_at__gte=timezone.now() - datetime.timedelta(hours=DEDUPE_HOURS)
        ).exclude(status=OutgoingEmail.Status.SKIPPED).exists():
            return None
        row = OutgoingEmail.objects.create(
            user=user if getattr(user, "pk", None) else None, to=to, template=template_key, category=t.category,
            subject=subject, text=text, html=html, headers=hdrs, key=key[:120])
        if urgent:
            transaction.on_commit(lambda: deliver(row.pk))
        return row
    except Exception:  # noqa: BLE001 - ایمیل نباید فراخوان را بشکند
        log.exception("mail.send failed")
        return None


# ---------------------------------------------------------------- ارسال
def _from_header(cfg) -> str:
    addr = (cfg.from_email if cfg and cfg.from_email else None) or settings.DEFAULT_FROM_EMAIL
    name = (cfg.from_name if cfg else "") or ""
    return f"{name} <{addr}>" if name else addr


def _sent_last_day(now) -> int:
    from .models import OutgoingEmail

    return OutgoingEmail.objects.filter(status=OutgoingEmail.Status.SENT, sent_at__gte=now - datetime.timedelta(hours=24)).count()


def _room(cfg, category: str, now) -> bool:
    limit = cfg.daily_limit if cfg else 200
    cap = limit if category == SECURITY else max(0, limit - RESERVE)
    return _sent_last_day(now) < cap


def deliver(pk: int, now=None) -> bool:
    """یک ایمیل صف‌شده را می‌فرستد؛ True اگر رفت. هرگز استثنا نمی‌دهد."""
    from .models import OutgoingEmail

    now = now or timezone.now()
    try:
        row = OutgoingEmail.objects.filter(pk=pk, status=OutgoingEmail.Status.QUEUED).first()
        if row is None:
            return False
        cfg = config()
        if not _room(cfg, row.category, now):
            row.next_try = now + datetime.timedelta(hours=1)  # سقف روزانه؛ بعداً دوباره
            row.save(update_fields=["next_try"])
            return False
        headers = dict(row.headers or {})
        if cfg and cfg.reply_to:
            headers.setdefault("Reply-To", cfg.reply_to)
        row.attempts += 1
        try:
            msg = EmailMultiAlternatives(row.subject, row.text, _from_header(cfg), [row.to], headers=headers,
                                         connection=_connection())
            msg.attach_alternative(row.html, "text/html")
            msg.send(fail_silently=False)
        except Exception as exc:  # noqa: BLE001
            row.error = _safe_error(exc)
            fatal = isinstance(exc, (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused))
            if fatal or row.attempts >= MAX_ATTEMPTS:
                row.status = OutgoingEmail.Status.FAILED
            else:
                row.next_try = now + datetime.timedelta(minutes=BACKOFF_MIN[min(row.attempts - 1, len(BACKOFF_MIN) - 1)])
            row.save()
            if cfg:
                cfg.last_error = row.error
                cfg.save(update_fields=["last_error"])
            return False
        row.status, row.sent_at, row.error = OutgoingEmail.Status.SENT, now, ""
        row.save()
        if cfg:
            cfg.last_ok, cfg.last_error = now, ""
            cfg.save(update_fields=["last_ok", "last_error"])
        return True
    except Exception:  # noqa: BLE001
        log.exception("mail.deliver failed")
        return False


def tick(now=None) -> dict:
    """کار دوره‌ای: صف را می‌فرستد (امنیتی اول) و دفتر قدیمی را پاک می‌کند."""
    from .models import OutgoingEmail

    now = now or timezone.now()
    OutgoingEmail.objects.filter(created_at__lt=now - datetime.timedelta(days=KEEP_DAYS)).delete()
    send_digests(now)
    sent = 0
    due = OutgoingEmail.objects.filter(status=OutgoingEmail.Status.QUEUED, next_try__lte=now)
    ids = sorted(due.values_list("pk", "category")[:200], key=lambda r: (r[1] != SECURITY, r[0]))[:BATCH]
    for pk, _cat in ids:
        sent += deliver(pk, now)
    return {"sent": sent}


def send_test(to: str) -> tuple[bool, str]:
    """ایمیل آزمایشی همزمان (برای دکمه‌ی پنل)؛ نتیجه را فوری و بدون صف نشان می‌دهد."""
    cfg = config()
    try:
        subject, html, text = render("mail_test", {})
        msg = EmailMultiAlternatives(subject, text, _from_header(cfg), [to],
                                     headers={"Auto-Submitted": "auto-generated"}, connection=_connection())
        msg.attach_alternative(html, "text/html")
        msg.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001
        return False, _safe_error(exc)
    return True, "ایمیل آزمایشی ارسال شد."


# ---------------------------------------------------------------- اعلان عمومی و خلاصه‌ی روزانه
DIGEST_HOUR, DIGEST_GAP_HOURS = 8, 20


def notice(user, title: str, body: str = "", *, url: str = "", label: str = "مشاهده", urgent: bool = False,
           key: str = "", to: str = ""):
    """اعلان متنی (دسته‌ی سرویس) با دکمه‌ی اختیاری. اگر کاربر «خلاصه‌ی روزانه» خواسته و فوری نیست، در خلاصه جمع می‌شود.

    برمی‌گرداند True اگر ایمیل یا خلاصه ثبت شد؛ هرگز استثنا نمی‌دهد.
    """
    from .models import DigestItem

    try:
        pref = _pref(user)
        if user is not None and not to and not urgent and pref is not None and pref.email_digest and can_email(user):
            DigestItem.objects.create(user=user, title=title[:200], body=body, url=url[:300])
            return True
        row = send("notice", user=user, to=to, key=key, urgent=urgent,
                   context={"title": title, "body": body, "url": url, "label": label})
        return bool(row is not None and row.status == "queued")
    except Exception:  # noqa: BLE001
        log.exception("mail.notice failed")
        return False


def send_digests(now=None) -> int:
    """ساعت ۸ صبح به بعد، برای هر کاربرِ دارای اعلان منتظر یک ایمیل خلاصه می‌فرستد (حداکثر یکی در ۲۰ ساعت)."""
    from collections import defaultdict

    from .models import DigestItem, OutgoingEmail

    now = now or timezone.now()
    if timezone.localtime(now).hour < DIGEST_HOUR:
        return 0
    groups = defaultdict(list)
    for it in DigestItem.objects.select_related("user").order_by("id")[:500]:
        groups[it.user_id].append(it)
    sent = 0
    for items in groups.values():
        user = items[0].user
        if OutgoingEmail.objects.filter(user=user, template="digest",
                                        created_at__gte=now - datetime.timedelta(hours=DIGEST_GAP_HOURS)).exists():
            continue
        row = send("digest", user=user, context={"items": [{"title": i.title, "body": i.body, "url": i.url} for i in items]})
        if row is not None:
            DigestItem.objects.filter(pk__in=[i.pk for i in items]).delete()
            sent += row.status == "queued"
    return sent
