from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm
from django.db.models import Count, Q

from databases.models import UserDatabase

from .models import AdminUser, OTPCode, SiteUser, normalize_mobile


class UserDatabaseInline(admin.TabularInline):
    model = UserDatabase
    fk_name = "owner"
    extra = 0
    can_delete = False
    fields = ["db_name", "plan", "status", "size_bytes", "expires_at"]
    readonly_fields = ["db_name", "plan", "status", "size_bytes", "expires_at"]
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class SiteUserForm(forms.ModelForm):
    class Meta:
        model = SiteUser
        fields = ["phone", "full_name", "email", "organization", "is_active"]

    def clean_phone(self):
        return normalize_mobile(self.cleaned_data["phone"])


@admin.register(SiteUser)
class SiteUserAdmin(admin.ModelAdmin):
    form = SiteUserForm
    list_display = ["phone", "full_name", "organization", "db_count", "is_active", "date_joined", "last_login"]
    list_filter = ["is_active", "date_joined"]
    search_fields = ["phone", "full_name", "organization", "email"]
    readonly_fields = ["date_joined", "last_login", "phone_verified_at"]
    fields = ["phone", "full_name", "email", "organization", "is_active", "phone_verified_at", "date_joined",
              "last_login"]
    inlines = [UserDatabaseInline]
    actions = ["deactivate", "activate"]
    ordering = ["-date_joined"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _dbs=Count("databases", filter=~Q(databases__status=UserDatabase.Status.DELETED)))

    @admin.display(description="پایگاه داده", ordering="_dbs")
    def db_count(self, obj):
        return obj._dbs

    def save_model(self, request, obj, form, change):
        obj.is_staff = False
        obj.is_superuser = False
        if not change:
            obj.set_unusable_password()
        super().save_model(request, obj, form, change)

    @admin.action(description="غیرفعال کردن حساب (ورود ممکن نیست)")
    def deactivate(self, request, queryset):
        n = queryset.update(is_active=False)
        self.message_user(request, f"{n} حساب غیرفعال شد. پایگاه‌های دادهٔ آن‌ها را جداگانه معلق کنید.", messages.SUCCESS)

    @admin.action(description="فعال کردن حساب")
    def activate(self, request, queryset):
        n = queryset.update(is_active=True)
        self.message_user(request, f"{n} حساب فعال شد.", messages.SUCCESS)


class AdminCreateForm(forms.ModelForm):
    password1 = forms.CharField(label="رمز عبور", widget=forms.PasswordInput, min_length=10)
    password2 = forms.CharField(label="تکرار رمز عبور", widget=forms.PasswordInput)

    class Meta:
        model = AdminUser
        fields = ["username", "full_name", "is_superuser"]

    def clean_username(self):
        u = (self.cleaned_data.get("username") or "").strip()
        if not u:
            raise forms.ValidationError("نام کاربری الزامی است.")
        return u

    def clean(self):
        c = super().clean()
        if c.get("password1") != c.get("password2"):
            self.add_error("password2", "دو رمز یکسان نیستند.")
        return c

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.is_staff = True
        obj.set_password(self.cleaned_data["password1"])
        if commit:
            obj.save()
        return obj


@admin.register(AdminUser)
class AdminUserAdmin(BaseUserAdmin):
    add_form = AdminCreateForm
    change_password_form = AdminPasswordChangeForm
    list_display = ["username", "full_name", "is_superuser", "is_active", "last_login"]
    list_filter = ["is_superuser", "is_active"]
    search_fields = ["username", "full_name"]
    ordering = ["username"]
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("اطلاعات", {"fields": ("full_name", "email")}),
        ("دسترسی‌ها", {"fields": ("is_active", "is_superuser", "groups", "user_permissions"),
                       "description": "مدیر کامل (superuser) به همه بخش‌ها دسترسی دارد. برای پشتیبان‌ها "
                                      "superuser را بردارید و فقط دسترسی‌های لازم را بدهید."}),
        ("تاریخ‌ها", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",),
                             "fields": ("username", "full_name", "password1", "password2", "is_superuser")}),)

    def save_model(self, request, obj, form, change):
        obj.is_staff = True
        super().save_model(request, obj, form, change)


@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = ["phone", "created_at", "expires_at", "attempts", "used_at", "sent_ok", "ip"]
    list_filter = ["sent_ok"]
    search_fields = ["phone", "ip"]
    readonly_fields = [f.name for f in OTPCode._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
