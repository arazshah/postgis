from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["-date_joined"]
    list_display = ["email", "full_name", "organization", "is_active", "is_staff", "date_joined"]
    list_filter = ["is_active", "is_staff"]
    search_fields = ["email", "full_name", "organization", "phone"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("اطلاعات", {"fields": ("full_name", "phone", "organization")}),
        ("دسترسی‌ها", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("تاریخ‌ها", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)
