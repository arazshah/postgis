from django import forms
from django.contrib import admin, messages
from django.template.defaultfilters import filesizeformat
from django.utils.html import format_html

from . import services
from .models import ActivityLog, DatabaseServer, Extension, Plan, UserDatabase
from .provisioner import ProvisionError


class DatabaseServerForm(forms.ModelForm):
    admin_password = forms.CharField(
        label="رمز کاربر ادمین", required=False, widget=forms.PasswordInput(render_value=False),
        help_text="فقط هنگام تغییر وارد کنید؛ رمزنگاری‌شده ذخیره می‌شود و هرگز نمایش داده نمی‌شود.")

    class Meta:
        model = DatabaseServer
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk and not cleaned.get("admin_password"):
            self.add_error("admin_password", "برای سرور جدید رمز ادمین الزامی است.")
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("admin_password"):
            obj.set_admin_password(self.cleaned_data["admin_password"])
        if commit:
            obj.save()
        return obj


@admin.register(DatabaseServer)
class DatabaseServerAdmin(admin.ModelAdmin):
    form = DatabaseServerForm
    list_display = ["name", "public_host", "health", "usage", "is_active", "is_default", "server_version",
                    "postgis_version", "last_check_at"]
    list_filter = ["is_active"]
    actions = ["test_connection"]
    readonly_fields = ["last_check_at", "last_check_ok", "last_check_message", "server_version", "postgis_version",
                       "created_at", "updated_at"]
    fieldsets = (
        ("اتصال مدیریتی (پنل ← سرور)", {
            "fields": ("name", "host", "port", "admin_user", "admin_password", "admin_database", "sslmode"),
            "description": "پنل با این اطلاعات به سرور وصل می‌شود و دیتابیس کاربران را می‌سازد. "
                           "کاربر ادمین باید superuser باشد.",
        }),
        ("اطلاعاتی که به کاربران نمایش داده می‌شود", {"fields": ("public_host", "public_port", "public_sslmode")}),
        ("ظرفیت و وضعیت", {"fields": ("is_active", "is_default", "max_databases", "disk_capacity_gb", "notes")}),
        ("آخرین بررسی", {"fields": ("last_check_at", "last_check_ok", "last_check_message", "server_version",
                                     "postgis_version", "created_at", "updated_at")}),
    )

    @admin.display(description="سلامت")
    def health(self, obj):
        if obj.last_check_ok is None:
            return "—"
        color = "#1a7f4b" if obj.last_check_ok else "#b42318"
        return format_html('<b style="color:{}">{}</b>', color, "سالم" if obj.last_check_ok else "خطا")

    @admin.display(description="دیتابیس‌ها")
    def usage(self, obj):
        return f"{obj.active_database_count()} / {obj.max_databases}"

    @admin.action(description="بررسی اتصال سرورهای انتخاب‌شده")
    def test_connection(self, request, queryset):
        for server in queryset:
            info = services.refresh_server(server)
            level = messages.SUCCESS if info.ok and "هشدار" not in info.message else (
                messages.WARNING if info.ok else messages.ERROR)
            extra = f" | PostgreSQL {info.server_version} | PostGIS {info.postgis_version or 'ندارد'}" if info.ok else ""
            self.message_user(request, f"{server.name}: {info.message}{extra}", level)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        info = services.refresh_server(obj)
        self.message_user(request, f"بررسی خودکار اتصال: {info.message}",
                          messages.SUCCESS if info.ok else messages.WARNING)


@admin.register(Extension)
class ExtensionAdmin(admin.ModelAdmin):
    list_display = ["title", "name", "is_default", "is_heavy", "is_active", "order"]
    list_editable = ["is_default", "is_heavy", "is_active", "order"]


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "quota_mb", "max_connections", "duration_days", "price_toman", "is_free",
                    "is_public", "is_default", "order"]
    list_editable = ["price_toman", "is_public", "order"]
    fieldsets = (
        (None, {"fields": ("name", "slug", "description", "order")}),
        ("منابع", {"fields": ("quota_mb", "max_connections", "statement_timeout_s", "temp_file_limit_mb",
                               "backup_retention_days", "allowed_extensions")}),
        ("مدت و قیمت", {"fields": ("duration_days", "price_toman", "is_free", "is_renewable"),
                        "description": "درگاه پرداخت فعلاً فعال نیست؛ پلن‌های پولی در سایت با دکمه «درخواست از پشتیبانی» "
                                       "نمایش داده می‌شوند و شما پلن پایگاه داده کاربر را از همین پنل تغییر می‌دهید."}),
        ("نمایش", {"fields": ("is_public", "is_default")}),
    )
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ["allowed_extensions"]


class ActivityInline(admin.TabularInline):
    model = ActivityLog
    extra = 0
    can_delete = False
    fields = ["created_at", "action", "message", "success", "user"]
    readonly_fields = fields
    ordering = ["-created_at"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(UserDatabase)
class UserDatabaseAdmin(admin.ModelAdmin):
    list_display = ["db_name", "owner", "server", "plan", "status", "size", "usage_pct", "expires_at", "created_at"]
    list_filter = ["status", "server", "plan"]
    search_fields = ["db_name", "label", "owner__email", "owner__full_name"]
    readonly_fields = ["owner", "server", "label", "db_name", "role_name", "size_bytes", "size_checked_at",
                       "last_error", "created_at", "deleted_at"]
    fields = ["owner", "server", "plan", "label", "db_name", "role_name", "status", "extensions", "size_bytes",
              "size_checked_at", "expires_at", "last_error", "created_at", "deleted_at"]
    filter_horizontal = ["extensions"]
    inlines = [ActivityInline]
    actions = ["suspend", "activate", "renew_now", "drop_now", "apply_plan_limits"]

    @admin.display(description="حجم")
    def size(self, obj):
        return filesizeformat(obj.size_bytes)

    @admin.display(description="مصرف")
    def usage_pct(self, obj):
        return f"{obj.usage_percent}%"

    def has_add_permission(self, request):
        return False  # ساخت فقط از طریق پنل کاربری تا روی سرور هم ساخته شود

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change and "plan" in form.changed_data and obj.is_live:
            try:
                services.provisioner_for(obj.server).apply_limits(obj.role_name, services.limits_for(obj.plan))
                services.logevent("plan", f"پلن به «{obj.plan.name}» تغییر کرد", user=request.user, database=obj)
                self.message_user(request, "محدودیت‌های پلن جدید روی سرور اعمال شد.", messages.SUCCESS)
            except ProvisionError as exc:
                self.message_user(request, f"پلن ذخیره شد ولی اعمال روی سرور ناموفق بود: {exc}", messages.ERROR)

    def _run(self, request, queryset, fn, ok_text):
        done = 0
        for db in queryset:
            try:
                fn(db)
                done += 1
            except (services.ServiceError, ProvisionError) as exc:
                self.message_user(request, f"{db.db_name}: {exc}", messages.ERROR)
        if done:
            self.message_user(request, f"{done} مورد {ok_text}.", messages.SUCCESS)

    @admin.action(description="تعلیق (غیرفعال کردن ورود)")
    def suspend(self, request, queryset):
        self._run(request, queryset.exclude(status=UserDatabase.Status.DELETED),
                  lambda db: services.set_status(db, UserDatabase.Status.SUSPENDED, request.user), "معلق شد")

    @admin.action(description="فعال‌سازی")
    def activate(self, request, queryset):
        self._run(request, queryset.exclude(status=UserDatabase.Status.DELETED),
                  lambda db: services.set_status(db, UserDatabase.Status.ACTIVE, request.user), "فعال شد")

    @admin.action(description="تمدید به اندازه مدت پلن")
    def renew_now(self, request, queryset):
        def fn(db):
            db.extend()
            db.save()
            services.logevent("renew", "تمدید توسط ادمین", user=request.user, database=db)
        self._run(request, queryset.exclude(status=UserDatabase.Status.DELETED), fn, "تمدید شد")

    @admin.action(description="اعمال دوباره محدودیت‌های پلن روی سرور")
    def apply_plan_limits(self, request, queryset):
        self._run(request, queryset.filter(status__in=UserDatabase.LIVE_STATUSES),
                  lambda db: services.provisioner_for(db.server).apply_limits(db.role_name,
                                                                              services.limits_for(db.plan)),
                  "به‌روز شد")

    @admin.action(description="حذف دائمی از سرور (غیرقابل بازگشت)")
    def drop_now(self, request, queryset):
        self._run(request, queryset.exclude(status=UserDatabase.Status.DELETED),
                  lambda db: services.delete_database(db, request.user, "حذف توسط ادمین"), "حذف شد")


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "action", "success", "user", "database", "message"]
    list_filter = ["action", "success"]
    search_fields = ["message", "user__email", "database__db_name"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
