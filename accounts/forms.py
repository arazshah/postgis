import re

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .models import User, normalize_mobile

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class PhoneForm(forms.Form):
    phone = forms.CharField(
        label="شماره موبایل", max_length=20,
        widget=forms.TextInput(attrs={"dir": "ltr", "inputmode": "tel", "autocomplete": "tel", "autofocus": True,
                                      "placeholder": "09121234567", "class": "mono"}))
    # فیلد تله برای ربات‌ها
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_phone(self):
        return normalize_mobile(self.cleaned_data["phone"])

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise ValidationError("درخواست نامعتبر است.")
        return ""


class VerifyForm(forms.Form):
    code = forms.CharField(
        label="کد تأیید", max_length=8,
        widget=forms.TextInput(attrs={"dir": "ltr", "inputmode": "numeric", "autocomplete": "one-time-code",
                                      "autofocus": True, "class": "mono otp-input"}))

    def __init__(self, *args, new_user: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.new_user = new_user
        if new_user:
            self.fields["full_name"] = forms.CharField(label="نام و نام خانوادگی", max_length=150)
            self.fields["organization"] = forms.CharField(label="دانشگاه / شرکت (اختیاری)", max_length=200,
                                                          required=False)
            self.fields["accept_terms"] = forms.BooleanField(
                label="قوانین استفاده را خوانده‌ام و می‌پذیرم", required=True,
                error_messages={"required": "پذیرفتن قوانین لازم است."})

    def clean_code(self):
        code = re.sub(r"\s", "", self.cleaned_data["code"].translate(_DIGITS))
        if not code.isdigit():
            raise ValidationError("کد فقط شامل عدد است.")
        return code


def _clean_email(value: str) -> str:
    email = (value or "").strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        raise ValidationError("ایمیل معتبر نیست. نمونه درست: name@example.com") from None
    return email


class EmailSignupForm(forms.Form):
    """ثبت‌نام با ایمیل و رمز عبور؛ فعلاً بدون ارسال ایمیل تأیید."""

    full_name = forms.CharField(label="نام و نام خانوادگی", max_length=150)
    email = forms.CharField(
        label="ایمیل", max_length=254,
        widget=forms.EmailInput(attrs={"dir": "ltr", "autocomplete": "email", "autofocus": True,
                                       "placeholder": "name@example.com"}))
    password = forms.CharField(
        label="رمز عبور", strip=False,
        widget=forms.PasswordInput(attrs={"dir": "ltr", "autocomplete": "new-password"}),
        help_text="دست‌کم ۸ نویسه؛ فقط عدد و رمزهای رایج پذیرفته نمی‌شود.")
    organization = forms.CharField(label="دانشگاه / شرکت (اختیاری)", max_length=200, required=False)
    accept_terms = forms.BooleanField(
        label="قوانین استفاده را خوانده‌ام و می‌پذیرم", required=True,
        error_messages={"required": "پذیرفتن قوانین لازم است."})
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_email(self):
        email = _clean_email(self.cleaned_data["email"])
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("با این ایمیل قبلاً حساب ساخته شده است. وارد شوید.")
        return email

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise ValidationError("درخواست نامعتبر است.")
        return ""

    def clean(self):
        data = super().clean()
        pw = data.get("password")
        if pw:
            probe = User(email=data.get("email") or None, full_name=data.get("full_name", ""))
            try:
                validate_password(pw, probe)
            except ValidationError as exc:
                self.add_error("password", exc)
        return data


class PasswordLoginForm(forms.Form):
    """ورود با ایمیل (یا موبایل) و رمز عبور."""

    identifier = forms.CharField(
        label="ایمیل یا موبایل", max_length=254,
        widget=forms.TextInput(attrs={"dir": "ltr", "autocomplete": "username", "autofocus": True,
                                      "placeholder": "name@example.com"}))
    password = forms.CharField(
        label="رمز عبور", strip=False,
        widget=forms.PasswordInput(attrs={"dir": "ltr", "autocomplete": "current-password"}))
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise ValidationError("درخواست نامعتبر است.")
        return ""

    def clean_identifier(self):
        return self.cleaned_data["identifier"].strip()


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "email", "organization"]
        labels = {"full_name": "نام و نام خانوادگی", "email": "ایمیل (اختیاری)", "organization": "دانشگاه / شرکت"}
        widgets = {"email": forms.EmailInput(attrs={"dir": "ltr"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and not self.instance.phone:
            self.fields["email"].label = "ایمیل (شناسه‌ی ورود)"

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            if not self.instance.phone:
                raise ValidationError("ایمیل شناسه‌ی ورود شماست و نمی‌تواند خالی باشد.")
            return None
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError("این ایمیل برای حساب دیگری ثبت شده است.")
        return email
