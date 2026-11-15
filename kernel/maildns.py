"""بررسی رکوردهای DNS دامنه‌ی فرستنده (SPF، DKIM، DMARC، MX): بدون این‌ها Gmail/Yahoo ایمیل را اسپم می‌کنند.

فقط می‌خواند (TXT/MX)؛ چیزی نمی‌نویسد و دامنه را از «نشانی فرستنده»ی تنظیم ایمیل می‌گیرد، نه از ورودی کاربر.
هر بررسی {key, title, status: ok|warn|bad, detail, fix} می‌دهد؛ `fix` همان رکوردی است که مدیر باید در DNS بگذارد.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass

from django.conf import settings
from django.utils import timezone

log = logging.getLogger(__name__)
COMMON_SELECTORS = ("default", "mail", "dkim", "selector1", "selector2", "s1", "s2", "google", "k1", "chabokan")
TIMEOUT, WEEK = 4, 7 * 24 * 3600
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class DnsError(Exception):
    pass


@dataclass
class Check:
    key: str
    title: str
    status: str
    detail: str
    fix: str = ""


def domain_of(address: str) -> str:
    d = (address or "").rpartition("@")[2].strip().lower().rstrip(".")
    return d if DOMAIN_RE.match(d) else ""


def _resolver():
    import dns.resolver

    r = dns.resolver.Resolver()
    r.lifetime = r.timeout = TIMEOUT
    return r


def _txt(name: str) -> list[str]:
    """رکوردهای TXT؛ [] اگر نباشد. خطای شبکه/زمان‌سنج = DnsError (نتیجه‌ی «نامعلوم»، نه «رکورد نیست»)."""
    import dns.exception
    import dns.resolver

    try:
        answers = _resolver().resolve(name, "TXT")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except (dns.exception.DNSException, OSError) as exc:
        raise DnsError(type(exc).__name__) from None
    return ["".join(p.decode("utf-8", "replace") for p in rdata.strings) for rdata in answers]


def _mx(name: str) -> list[str]:
    import dns.exception
    import dns.resolver

    try:
        return [str(r.exchange).rstrip(".") for r in _resolver().resolve(name, "MX")]
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except (dns.exception.DNSException, OSError) as exc:
        raise DnsError(type(exc).__name__) from None


def _exists(domain: str) -> bool:
    """False فقط وقتی DNS صریحاً می‌گوید دامنه وجود ندارد (NXDOMAIN)؛ خطای شبکه = فرض وجود (بررسی‌های بعدی «نامعلوم» می‌شوند)."""
    import dns.exception
    import dns.resolver

    try:
        _resolver().resolve(domain, "SOA")
    except dns.resolver.NXDOMAIN:
        return False
    except (dns.exception.DNSException, OSError):
        return True
    return True


def _unknown(key: str, title: str) -> Check:
    return Check(key, title, "warn", "پرس‌وجوی DNS ناموفق بود (زمان‌سنج یا شبکه)؛ دوباره بررسی کنید.")


def check_spf(domain: str) -> Check:
    title = "SPF (اجازه‌ی فرستادن)"
    try:
        recs = [t for t in _txt(domain) if t.lower().startswith("v=spf1")]
    except DnsError:
        return _unknown("spf", title)
    fix = f'در DNS دامنه‌ی {domain} یک رکورد TXT بگذارید: v=spf1 mx a include:<دامنه‌ی سرویس‌دهنده> ~all (مقدار include را از پنل سرویس ایمیل بگیرید).'
    if not recs:
        return Check("spf", title, "bad", "رکورد SPF پیدا نشد.", fix)
    if len(recs) > 1:
        return Check("spf", title, "bad", "بیش از یک رکورد SPF هست؛ استاندارد فقط یکی را می‌پذیرد و هر دو نادیده گرفته می‌شود.",
                     "رکوردهای SPF را در یک رکورد ادغام کنید.")
    spf = recs[0].lower()
    permissive = bool(re.search(r"(^|\s)\+?all\b", spf)) and not re.search(r"[~-]all\b", spf)
    if permissive or "?all" in spf:
        return Check("spf", title, "bad", "SPF همه را مجاز می‌کند (+all/?all) و عملاً بی‌اثر است.", "پایان رکورد را به ~all یا -all تغییر دهید.")
    if not re.search(r"[~-]all\b", spf) and "redirect=" not in spf:
        return Check("spf", title, "warn", "SPF پایان‌دهنده‌ی ~all یا -all ندارد.", "در انتهای رکورد ~all بگذارید.")
    lookups = len(re.findall(r"\b(include:|a\b|mx\b|ptr\b|exists:|redirect=)", spf))
    if lookups > 10:
        return Check("spf", title, "warn", f"SPF حدود {lookups} پرس‌وجو دارد و از سقف ۱۰ استاندارد می‌گذرد.", "include های غیرضروری را حذف کنید.")
    return Check("spf", title, "ok", "رکورد SPF معتبر است.")


def check_dkim(domain: str, selector: str = "") -> Check:
    title = "DKIM (امضای ایمیل)"
    names = [selector] if selector else list(COMMON_SELECTORS)
    unknown = False
    for sel in names:
        try:
            recs = _txt(f"{sel}._domainkey.{domain}")
        except DnsError:
            unknown = True
            continue
        for t in recs:
            low = t.lower().replace(" ", "")
            if "v=dkim1" in low or "p=" in low:
                if re.search(r"p=(;|$)", low):
                    return Check("dkim", title, "bad", f"کلید DKIM «{sel}» باطل شده (p خالی).", "کلید تازه از پنل سرویس ایمیل بگیرید.")
                return Check("dkim", title, "ok", f"رکورد DKIM با selector «{sel}» پیدا شد.")
    if unknown and not selector:
        return _unknown("dkim", title)
    fix = "در پنل سرویس ایمیل بخش DKIM را فعال کنید و رکورد TXT داده‌شده را در DNS بگذارید؛ سپس selector را در «تنظیم ایمیل» بنویسید."
    if selector:
        return Check("dkim", title, "bad", f"رکورد {selector}._domainkey.{domain} پیدا نشد.", fix)
    return Check("dkim", title, "warn", "با نام‌های رایج selector رکورد DKIM پیدا نشد؛ اگر selector را می‌دانید در تنظیم بنویسید، وگرنه DKIM را فعال کنید.", fix)


def check_dmarc(domain: str) -> Check:
    title = "DMARC (سیاست دامنه)"
    try:
        recs = [t for t in _txt(f"_dmarc.{domain}") if t.lower().replace(" ", "").startswith("v=dmarc1")]
    except DnsError:
        return _unknown("dmarc", title)
    fix = f"رکورد TXT برای _dmarc.{domain} بگذارید: v=DMARC1; p=none; rua=mailto:dmarc@{domain}"
    if not recs:
        return Check("dmarc", title, "bad", "رکورد DMARC پیدا نشد؛ Gmail و Yahoo برای ارسال انبوه آن را می‌خواهند.", fix)
    low = recs[0].lower().replace(" ", "")
    pol = re.search(r"(?:^|;)p=(none|quarantine|reject)", low)
    if not pol:
        return Check("dmarc", title, "bad", "رکورد DMARC سیاست (p=) معتبر ندارد.", fix)
    if pol.group(1) == "none":
        return Check("dmarc", title, "warn", "سیاست DMARC فقط پایش است (p=none)؛ برای شروع درست است.",
                     "بعد از چند هفته گزارش بدون مشکل، p=quarantine بگذارید.")
    return Check("dmarc", title, "ok", f"DMARC با سیاست {pol.group(1)} فعال است.")


def check_mx(domain: str) -> Check:
    title = "MX (دریافت ایمیل)"
    try:
        mx = _mx(domain)
    except DnsError:
        return _unknown("mx", title)
    if not mx:
        return Check("mx", title, "warn", "MX ندارد؛ پاسخ‌ها و ایمیل‌های برگشتی به این دامنه نمی‌رسد.", "MX را از پنل سرویس ایمیل بگیرید.")
    return Check("mx", title, "ok", f"MX: {mx[0]}")


def run(domain: str, selector: str = "") -> list[Check]:
    if not _exists(domain):
        # اگر همه‌چیز «نیست» بگوییم ولی علت خرابی resolver سرور یا ثبت‌نشدن دامنه باشد، مدیر را گمراه می‌کنیم
        return [Check("domain", "وجود دامنه در DNS", "bad",
                      f"DNS می‌گوید دامنه‌ی {domain} وجود ندارد (NXDOMAIN).",
                      "دامنه و nameserver آن را در ثبت‌کننده بررسی کنید؛ اگر دامنه درست کار می‌کند، resolver (DNS) خود سرور پنل مشکل دارد.")]
    return [check_spf(domain), check_dkim(domain, selector), check_dmarc(domain), check_mx(domain)]


def overall(checks: list[Check]) -> str:
    states = {c.status for c in checks}
    return "bad" if "bad" in states else "warn" if "warn" in states else "ok"


def domain_for(cfg) -> str:
    return domain_of((cfg.from_email if cfg else "") or getattr(settings, "DEFAULT_FROM_EMAIL", ""))


def refresh(cfg=None) -> list[dict]:
    """بررسی را اجرا و نتیجه را روی تنظیم ذخیره می‌کند (برای کارت داشبورد و صفحه‌ی تنظیم)."""
    from . import mail

    cfg = cfg or mail.config()
    if cfg is None:
        return []
    domain = domain_for(cfg)
    if not domain:
        return []
    checks = run(domain, cfg.dkim_selector)
    cfg.dns_report = [asdict(c) for c in checks]
    cfg.dns_status, cfg.dns_checked_at = overall(checks), timezone.now()
    cfg.save(update_fields=["dns_report", "dns_status", "dns_checked_at"])
    return cfg.dns_report


def tick(now=None) -> str:
    """هفته‌ای یک‌بار (و فقط وقتی ارسال ایمیل فعال است) دوباره می‌سنجد تا حذف/خرابی رکورد زود دیده شود."""
    from . import mail

    cfg = mail.config()
    now = now or timezone.now()
    if cfg is None or not cfg.enabled:
        return "خاموش"
    if cfg.dns_checked_at and (now - cfg.dns_checked_at).total_seconds() < WEEK:
        return "تازه"
    refresh(cfg)
    return cfg.dns_status
