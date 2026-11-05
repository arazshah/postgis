"""فرم عمومی «تماس و درخواست جلسه»: اعتبارسنجی، محدودیت تعداد و اطلاع‌رسانی به مدیر."""
import hashlib
import logging

from django import forms
from django.core.cache import cache

from accounts.models import normalize_mobile

from .models import ContactRequest

log = logging.getLogger(__name__)
PER_IP_HOUR = 5
PER_PHONE_DAY = 3


class ContactForm(forms.ModelForm):
    # تله‌ی ربات: کاربر واقعی هرگز این فیلد را نمی‌بیند و پر نمی‌کند
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    class Meta:
        model = ContactRequest
        fields = ("topic", "name", "phone", "organization", "email", "preferred_time", "message")
        labels = {"phone": "شماره موبایل", "message": "توضیح (اختیاری)", "preferred_time": "زمان مناسب برای تماس (اختیاری)"}
        widgets = {
            "topic": forms.RadioSelect,
            "name": forms.TextInput(attrs={"autocomplete": "name"}),
            "phone": forms.TextInput(attrs={"dir": "ltr", "inputmode": "tel", "autocomplete": "tel", "placeholder": "09123456789"}),
            "organization": forms.TextInput(attrs={"autocomplete": "organization"}),
            "email": forms.EmailInput(attrs={"dir": "ltr", "autocomplete": "email"}),
            "preferred_time": forms.TextInput(attrs={"placeholder": "مثلاً یکشنبه عصر"}),
            "message": forms.Textarea(attrs={"rows": 4, "maxlength": 2000}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["topic"].choices = ContactRequest.Topic.choices
        self.fields["topic"].initial = ContactRequest.Topic.DEMO
        self.fields["topic"].label = "درباره‌ی چه چیزی می‌خواهید صحبت کنیم؟"
        self.fields["name"].required = True
        self.fields["phone"].required = True

    def clean_name(self):
        name = " ".join((self.cleaned_data.get("name") or "").split())
        if len(name) < 2:
            raise forms.ValidationError("نام را بنویسید.")
        return name

    def clean_phone(self):
        try:
            return normalize_mobile(self.cleaned_data.get("phone") or "")
        except Exception as exc:  # noqa: BLE001
            raise forms.ValidationError("شماره‌ی موبایل معتبر نیست؛ مثلاً ۰۹۱۲۳۴۵۶۷۸۹.") from exc

    def clean_message(self):
        return (self.cleaned_data.get("message") or "").strip()

    def clean(self):
        c = super().clean()
        if c.get("website"):  # ربات
            raise forms.ValidationError("درخواست پذیرفته نشد.")
        return c


def _ip_hash(ip: str | None) -> str:
    return hashlib.sha256(f"contact:{ip or ''}".encode()).hexdigest()[:16]


def throttled(ip: str | None, phone: str = "") -> str:
    """پیام خطا اگر سقف تعداد پر شده باشد؛ وگرنه خالی. شمارنده با هر بررسی موفق بالا می‌رود."""
    k_ip = f"contact:ip:{_ip_hash(ip)}"
    if cache.get(k_ip, 0) >= PER_IP_HOUR:
        return "تعداد درخواست‌های این شبکه در یک ساعت گذشته زیاد بوده؛ کمی بعد دوباره امتحان کنید یا تماس بگیرید."
    if phone:
        k_ph = f"contact:ph:{hashlib.sha256(phone.encode()).hexdigest()[:16]}"
        if cache.get(k_ph, 0) >= PER_PHONE_DAY:
            return "برای این شماره چند درخواست ثبت شده؛ در اولین فرصت با شما تماس می‌گیریم."
    return ""


def _bump(ip: str | None, phone: str) -> None:
    for key, ttl in ((f"contact:ip:{_ip_hash(ip)}", 3600),
                     (f"contact:ph:{hashlib.sha256(phone.encode()).hexdigest()[:16]}", 86400)):
        cache.add(key, 0, ttl)
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, ttl)


def submit(form: ContactForm, user, ip: str | None) -> ContactRequest:
    """ثبت درخواست و اطلاع‌رسانی (پیامک/ایمیل به مدیر)؛ خطای اطلاع‌رسانی ثبت را خراب نمی‌کند."""
    obj = form.save(commit=False)
    obj.user = user if getattr(user, "is_authenticated", False) else None
    obj.ip_hash = _ip_hash(ip)
    obj.save()
    _bump(ip, obj.phone)
    try:
        from .alerts import notify_admins

        text = (f"{obj.name} ({obj.phone}) · {obj.get_topic_display()}"
                + (f" · {obj.organization}" if obj.organization else "")
                + (f"\nزمان: {obj.preferred_time}" if obj.preferred_time else "")
                + (f"\n{obj.message[:400]}" if obj.message else ""))
        notify_admins("درخواست تماس/جلسه‌ی تازه", text)
    except Exception:  # noqa: BLE001
        log.exception("contact notify failed")
    return obj
