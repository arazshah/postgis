import re

from django import forms
from django.core.exceptions import ValidationError

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
            self.fields["organization"] = forms.CharField(label="دانشگاه / سازمان (اختیاری)", max_length=200,
                                                          required=False)
            self.fields["accept_terms"] = forms.BooleanField(
                label="قوانین استفاده را خوانده‌ام و می‌پذیرم", required=True,
                error_messages={"required": "پذیرفتن قوانین لازم است."})

    def clean_code(self):
        code = re.sub(r"\s", "", self.cleaned_data["code"].translate(_DIGITS))
        if not code.isdigit():
            raise ValidationError("کد فقط شامل عدد است.")
        return code


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "email", "organization"]
        labels = {"full_name": "نام و نام خانوادگی", "email": "ایمیل (اختیاری)", "organization": "دانشگاه / سازمان"}
        widgets = {"email": forms.EmailInput(attrs={"dir": "ltr"})}

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            return None
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError("این ایمیل برای حساب دیگری ثبت شده است.")
        return email
