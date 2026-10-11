from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import OTPCode, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["-date_joined"]
    list_display = ["phone", "full_name", "organization", "email", "is_active", "is_staff", "date_joined"]
    list_filter = ["is_active", "is_staff"]
    search_fields = ["phone", "full_name", "organization", "email"]
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("اطلاعات", {"fields": ("full_name", "email", "organization", "phone_verified_at")}),
        ("دسترسی‌ها", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("تاریخ‌ها", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("phone", "password1", "password2")}),)


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
