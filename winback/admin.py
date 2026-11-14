from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.utils.html import format_html

from kernel import stepup
from kernel.plugins import registry

from . import routes, services
from .models import Batch, Message, Route


class RouteForm(forms.ModelForm):
    gift_plugin = forms.ChoiceField(label="پلاگین هدیه", required=False)

    class Meta:
        model = Route
        fields = ("enabled", "template_id", "gift_kind", "gift_plugin", "gift_days")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["gift_plugin"].choices = [("", "—")] + [(p.id, p.name) for p in registry.plugins.values() if p.kind != "system"]

    def clean(self):
        data = super().clean()
        if data.get("enabled") and not (data.get("template_id") or "").strip().isdigit():
            raise forms.ValidationError("برای روشن‌کردن مسیر، شناسه‌ی عددی قالب تأییدشده‌ی sms.ir را بگذارید.")
        if data.get("gift_kind") == Route.Gift.TRIAL and not data.get("gift_plugin"):
            raise forms.ValidationError("برای هدیه‌ی آزمایش، پلاگین را انتخاب کنید.")
        return data


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    form = RouteForm
    list_display = ["title", "enabled", "template_id", "gift_kind", "sent", "uplift"]
    readonly_fields = ["goal", "template_text", "params_help"]
    fields = ["goal", "enabled", "template_id", "template_text", "params_help", "gift_kind", "gift_plugin", "gift_days"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        services.sync_routes()
        return super().get_queryset(request)

    @admin.display(description="مسیر")
    def title(self, obj):
        return routes.name_of(obj.key)

    @admin.display(description="هدف")
    def goal(self, obj):
        return routes.DEFS[obj.key].goal

    @admin.display(description="متن قالب برای ساخت در sms.ir")
    def template_text(self, obj):
        d = routes.DEFS[obj.key]
        return format_html("<pre dir='rtl' style='white-space:pre-wrap'>{}</pre><small>حدود {} بخش پیامک</small>",
                           d.template, routes.segments(routes.render(d.template, {"NAME": "علی", "LINK": "https://postgis.ir/r/Ab3xK9aQ/",
                                                                                  "STOP": "https://postgis.ir/r/Ab3xK9aQ/stop/", "DB": "پایگاه من", "DAYS": "45", "AMOUNT": "490,000"})))

    @admin.display(description="پارامترهای قالب")
    def params_help(self, obj):
        return format_html("<code dir='ltr'>{}</code>", "  ".join(f"#{p}#" for p in routes.DEFS[obj.key].params))

    @admin.display(description="ارسال‌شده")
    def sent(self, obj):
        return services.results(obj.key)["sent_total"]

    @admin.display(description="اثر واقعی (امتیاز بازگشت نسبت به کنترل)")
    def uplift(self, obj):
        r = services.results(obj.key)
        if r["uplift"] is None:
            return "هنوز داده‌ی کافی نیست"
        return f"{r['uplift'] * 100:+.1f}٪ (پیام {r['rate_sent'] * 100:.1f}٪ در برابر کنترل {r['rate_control'] * 100:.1f}٪)"


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ["route", "created_at", "status", "count", "control", "segments_cost"]
    list_filter = ["status", "route"]
    readonly_fields = ["route", "status", "approved_by", "approved_at", "preview"]
    fields = readonly_fields
    actions = ["approve_batches", "cancel_batches"]

    def has_add_permission(self, request):
        return False

    @admin.display(description="گیرنده‌ی واقعی")
    def count(self, obj):
        return obj.messages.exclude(status__in=[Message.Status.CONTROL, Message.Status.SKIPPED]).count()

    @admin.display(description="گروه کنترل")
    def control(self, obj):
        return obj.messages.filter(status=Message.Status.CONTROL).count()

    @admin.display(description="بخش پیامک (برآورد هزینه)")
    def segments_cost(self, obj):
        first = obj.messages.exclude(status=Message.Status.CONTROL).first()
        return self.count(obj) * routes.segments(services.preview(first)) if first else 0

    @admin.display(description="نمونه‌ی پیام‌ها")
    def preview(self, obj):
        rows = [format_html("<li><b>{}</b>: {}</li>", m.phone, services.preview(m)) for m in obj.messages.exclude(status=Message.Status.CONTROL)[:8]]
        return format_html("<ul dir='rtl'>{}</ul>", format_html("".join(str(r) for r in rows)))

    @admin.action(description="تأیید و زمان‌بندی ارسال (در بهترین ساعت هر کاربر)")
    def approve_batches(self, request, queryset):
        if not stepup.ok(request):
            return redirect(stepup.url(request))
        total = sum(services.approve(b, request.user) for b in queryset.filter(status=Batch.Status.PENDING))
        self.message_user(request, f"{total} پیام زمان‌بندی شد؛ هر کدام در بهترین ساعت کاربرش می‌رود.", messages.SUCCESS)

    @admin.action(description="لغو دسته")
    def cancel_batches(self, request, queryset):
        for b in queryset:
            services.cancel(b)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["route_key", "phone", "status", "send_at", "sent_at", "clicked_at", "returned_at", "paid_toman"]
    list_filter = ["route_key", "status"]
    search_fields = ["phone"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
