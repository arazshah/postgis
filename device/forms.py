from django import forms
from django.core.exceptions import ValidationError

from . import services

_CTL = {"autocomplete": "off"}


class LoginForm(forms.Form):
    identifier = forms.CharField(
        label="نام کاربری یا موبایل", max_length=150,
        widget=forms.TextInput(attrs={"dir": "ltr", "autocomplete": "username", "autofocus": True,
                                      "autocapitalize": "none", "spellcheck": "false"}))
    password = forms.CharField(label="رمز عبور", max_length=128, strip=False,
                               widget=forms.PasswordInput(attrs={"dir": "ltr", "autocomplete": "current-password"}))


class PasswordChangeForm(forms.Form):
    old = forms.CharField(label="رمز فعلی", strip=False,
                          widget=forms.PasswordInput(attrs={"dir": "ltr", "autocomplete": "current-password"}))
    new1 = forms.CharField(label="رمز تازه", strip=False, help_text="دست‌کم ۸ نویسه؛ نه فقط عدد و نه رمز رایج.",
                           widget=forms.PasswordInput(attrs={"dir": "ltr", "autocomplete": "new-password"}))
    new2 = forms.CharField(label="تکرار رمز تازه", strip=False,
                           widget=forms.PasswordInput(attrs={"dir": "ltr", "autocomplete": "new-password"}))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_old(self):
        if not self.user.check_password(self.cleaned_data["old"]):
            raise ValidationError("رمز فعلی درست نیست.")
        return self.cleaned_data["old"]

    def clean(self):
        data = super().clean()
        n1, n2 = data.get("new1"), data.get("new2")
        if n1 and n2 and n1 != n2:
            self.add_error("new2", "تکرار رمز با رمز تازه یکی نیست.")
        elif n1:
            try:
                services.check_new_password(n1, self.user)
            except ValidationError as exc:
                self.add_error("new1", exc)
        return data


class UserForm(forms.Form):
    """ساخت و ویرایش کاربر (ویرایش: نام کاربری و رمز در فرم نیست)."""

    username = forms.CharField(label="نام کاربری", max_length=30,
                               widget=forms.TextInput(attrs={"dir": "ltr", "autocapitalize": "none", **_CTL}))
    full_name = forms.CharField(label="نام و نام خانوادگی", max_length=150, required=False)
    organization = forms.CharField(label="واحد / سازمان", max_length=200, required=False)
    phone = forms.CharField(label="شماره‌ی موبایل", max_length=20,
                            help_text="اشتراک پایگاه داده بین همکاران با شماره‌ی موبایل انجام می‌شود؛ ورود هم با آن ممکن است.",
                            widget=forms.TextInput(attrs={"dir": "ltr", "inputmode": "tel", "placeholder": "09121234567"}))
    password = forms.CharField(label="رمز موقت", max_length=128, required=False, strip=False,
                               widget=forms.TextInput(attrs={"dir": "ltr", "class": "mono", **_CTL}),
                               help_text="کاربر در اولین ورود باید رمز خودش را بگذارد.")
    role = forms.ChoiceField(label="نقش", choices=[("user", "کاربر"), ("admin", "مدیر")], initial="user",
                             widget=forms.RadioSelect)
