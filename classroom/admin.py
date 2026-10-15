from django.contrib import admin, messages
from django.utils.html import format_html

from . import services
from .models import Classroom, Contract, ContractRequest, Enrollment


@admin.register(ContractRequest)
class ContractRequestAdmin(admin.ModelAdmin):
    list_display = ("institution", "name", "phone", "students", "course", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("institution", "name", "phone", "course")
    list_editable = ("status",)
    readonly_fields = ("created_at",)


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("institution", "number", "seats", "used", "starts_at", "ends_at", "total", "is_active")
    list_filter = ("is_active",)
    search_fields = ("institution", "number", "teacher_phones")
    filter_horizontal = ("teachers",)
    fieldsets = (
        (None, {"fields": ("institution", "number", "request", "is_active")}),
        ("ظرفیت و مالی", {"fields": ("seats", "price_per_seat_toman", "quota_mb")}),
        ("ترم", {"fields": ("starts_at", "ends_at")}),
        ("استادها", {"fields": ("teacher_phones", "teachers"),
                     "description": "موبایل استادها را هر کدام در یک خط بنویسید؛ با ورود به سایت، بخش «کلاس‌های من» "
                                    "برایشان باز می‌شود و تا سقف صندلی‌ها کلاس می‌سازند."}),
        (None, {"fields": ("notes",)}),
    )

    @admin.display(description="استفاده‌شده")
    def used(self, obj):
        return f"{obj.used_seats} / {obj.seats}"

    @admin.display(description="مبلغ کل (تومان)")
    def total(self, obj):
        return f"{obj.total_toman:,}"


class EnrollmentInline(admin.TabularInline):
    model = Enrollment
    extra = 0
    fields = ("full_name", "student_no", "student", "database", "archive", "joined_at")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ("title", "teacher", "contract", "students", "code_link", "status", "is_open", "created_at")
    list_filter = ("status", "template")
    search_fields = ("title", "code", "teacher__phone", "contract__institution")
    inlines = [EnrollmentInline]
    actions = ["archive_now"]
    readonly_fields = ("code", "archived_at")

    @admin.display(description="دانشجو")
    def students(self, obj):
        return f"{obj.enrollments.count()} / {obj.capacity}"

    @admin.display(description="کد")
    def code_link(self, obj):
        return format_html('<a href="/class/join/{}/" target="_blank">{}</a>', obj.code, obj.code)

    @admin.action(description="بایگانی کلاس‌های انتخاب‌شده (بکاپ پایگاه داده دانشجوها)")
    def archive_now(self, request, queryset):
        for c in queryset.filter(status=Classroom.Status.ACTIVE):
            n = services.archive(c)
            self.message_user(request, f"{c.title}: {n} بکاپ در صف.", messages.SUCCESS)
