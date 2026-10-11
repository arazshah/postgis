from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm

from .models import User


class SignupForm(forms.ModelForm):
    password1 = forms.CharField(label="رمز عبور", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="تکرار رمز عبور", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    accept_terms = forms.BooleanField(label="قوانین استفاده از سرویس را خوانده‌ام و می‌پذیرم", required=True)
    # فیلد تله برای ربات‌ها؛ کاربر واقعی آن را نمی‌بیند
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = User
        fields = ["full_name", "email", "organization"]
        labels = {"full_name": "نام و نام خانوادگی", "email": "ایمیل", "organization": "دانشگاه / سازمان (اختیاری)"}

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("با این ایمیل قبلاً ثبت‌نام شده است.")
        return email

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("درخواست نامعتبر است.")
        return ""

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "دو رمز عبور یکسان نیستند.")
        if p1:
            try:
                password_validation.validate_password(p1, User(email=cleaned.get("email", "")))
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label="ایمیل", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))
    password = forms.CharField(label="رمز عبور", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    error_messages = {
        "invalid_login": "ایمیل یا رمز عبور اشتباه است.",
        "inactive": "این حساب غیرفعال شده است.",
    }

    def clean(self):
        email = (self.cleaned_data.get("username") or "").lower()
        password = self.cleaned_data.get("password")
        if email and password:
            self.user_cache = authenticate(self.request, username=email, password=password)
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "phone", "organization"]
        labels = {"full_name": "نام و نام خانوادگی", "phone": "موبایل", "organization": "دانشگاه / سازمان"}


class FaPasswordChangeForm(PasswordChangeForm):
    pass
