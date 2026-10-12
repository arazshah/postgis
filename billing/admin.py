from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from . import services
from .models import Invoice, PlanVoucher


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["number", "user", "title_col", "amount_col", "method", "status_col", "created_at", "paid_at"]
    list_filter = ["status", "method", "kind", "plan"]
    search_fields = ["number", "user__phone", "user__full_name", "tracking_code", "payer_card_last4", "provider_id", "gateway_ref"]
    date_hierarchy = "created_at"
    actions = ["approve", "reject_selected", "check_gateway", "reapply"]
    readonly_fields = ["number", "user", "kind", "plan", "database", "amount_toman", "method", "gateway", "provider_id",
                       "gateway_ref", "pay_url", "provider_status", "receipt_preview", "payer_card_last4", "tracking_code",
                       "paid_at_claimed", "reviewed_by", "created_at", "expires_at", "paid_at", "applied_at"]
    fields = ["number", "user", "kind", "plan", "database", "amount_toman", "status", "method",
              "receipt_preview", "payer_card_last4", "tracking_code", "paid_at_claimed",
              "gateway", "provider_id", "gateway_ref", "pay_url", "provider_status", "note", "reviewed_by",
              "created_at", "expires_at", "paid_at", "applied_at"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "plan", "database")

    def has_add_permission(self, request):
        return False

    @admin.display(description="شرح")
    def title_col(self, obj):
        return obj.title

    @admin.display(description="مبلغ (تومان)", ordering="amount_toman")
    def amount_col(self, obj):
        return f"{obj.amount_toman:,}"

    @admin.display(description="وضعیت", ordering="status")
    def status_col(self, obj):
        colors = {"paid": "#1a7f4b", "review": "#b26b00", "pending": "#4B6269"}
        return format_html('<b style="color:{}">{}</b>', colors.get(obj.status, "#b42318"), obj.get_status_display())

    @admin.display(description="رسید")
    def receipt_preview(self, obj):
        if not obj.receipt:
            return "—"
        url = reverse("billing:receipt_file", args=[obj.number])
        return format_html('<a href="{}" target="_blank"><img src="{}" style="max-width:320px;max-height:420px;'
                           'border:1px solid #ccc;border-radius:6px"></a>', url, url)

    def save_model(self, request, obj, form, change):
        # اگر مدیر وضعیت را دستی «پرداخت‌شده» کرد، از مسیر رسمی اعمال شود
        if change and "status" in form.changed_data and obj.status == Invoice.Status.PAID:
            obj.status = form.initial.get("status", Invoice.Status.REVIEW)
            super().save_model(request, obj, form, change)
            services.mark_paid(obj, actor=request.user)
            self.message_user(request, "فاکتور پرداخت‌شده ثبت و پلن اعمال شد.", messages.SUCCESS)
            return
        super().save_model(request, obj, form, change)

    @admin.action(description="تأیید پرداخت و اعمال پلن")
    def approve(self, request, queryset):
        n = 0
        for inv in queryset.exclude(status=Invoice.Status.PAID):
            inv = services.mark_paid(inv, actor=request.user)
            n += 1
            if not inv.applied_at:
                self.message_user(request, f"{inv.number}: پرداخت ثبت شد ولی اعمال پلن ناموفق بود — یادداشت را ببینید.",
                                  messages.WARNING)
        self.message_user(request, f"{n} فاکتور تأیید شد.", messages.SUCCESS)

    @admin.action(description="رد رسید")
    def reject_selected(self, request, queryset):
        n = 0
        for inv in queryset.exclude(status=Invoice.Status.PAID):
            services.reject(inv, request.user, "رسید با واریزی تطبیق نداشت.")
            n += 1
        self.message_user(request, f"{n} فاکتور رد شد و به کاربر اطلاع داده شد.", messages.SUCCESS)

    @admin.action(description="استعلام و تأیید دوباره از درگاه")
    def check_gateway(self, request, queryset):
        for inv in queryset.filter(method=Invoice.Method.GATEWAY):
            inv = services.verify_gateway(inv)
            self.message_user(request, f"{inv.number}: {inv.get_status_display()} ({inv.provider_status or '—'})")

    @admin.action(description="اعمال دوباره پلن (برای پرداخت‌شده‌های اعمال‌نشده)")
    def reapply(self, request, queryset):
        for inv in queryset.filter(status=Invoice.Status.PAID, applied_at__isnull=True):
            try:
                services.apply_invoice(inv)
                self.message_user(request, f"{inv.number}: اعمال شد.", messages.SUCCESS)
            except Exception as exc:  # noqa: BLE001
                self.message_user(request, f"{inv.number}: {exc}", messages.ERROR)


@admin.register(PlanVoucher)
class PlanVoucherAdmin(admin.ModelAdmin):
    list_display = ["user", "plan", "invoice", "used_by", "created_at", "used_at"]
    list_filter = ["plan"]
    search_fields = ["user__phone"]
    raw_id_fields = ["user", "invoice", "used_by"]
