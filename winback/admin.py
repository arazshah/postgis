from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.html import format_html

from kernel import stepup
from kernel.plugins import registry

from . import routes, services
from .models import Batch, Message, Referral, Route


class RouteForm(forms.ModelForm):
    gift_plugin = forms.ChoiceField(label="پلاگین هدیه", required=False)

    class Meta:
        model = Route
        fields = ("enabled", "template_id", "template_id_b", "gift_kind", "gift_plugin", "gift_days", "gift_percent")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["gift_plugin"].choices = [("", "—")] + [(p.id, p.name) for p in registry.plugins.values() if p.kind != "system"]

    def clean(self):
        data = super().clean()
        if data.get("enabled") and not (data.get("template_id") or "").strip().isdigit():
            raise forms.ValidationError("برای روشن‌کردن مسیر، شناسه‌ی عددی قالب تأییدشده‌ی sms.ir را بگذارید.")
        if (data.get("template_id_b") or "").strip() and not data["template_id_b"].strip().isdigit():
            raise forms.ValidationError("شناسه‌ی قالب B باید عدد باشد.")
        if (data.get("template_id_b") or "").strip() and not (data.get("template_id") or "").strip():
            raise forms.ValidationError("برای آزمون A/B اول قالب A را بگذارید.")
        if data.get("gift_kind") == Route.Gift.TRIAL and not data.get("gift_plugin"):
            raise forms.ValidationError("برای هدیه‌ی آزمایش، پلاگین را انتخاب کنید.")
        return data


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    form = RouteForm
    list_display = ["title", "enabled", "template_id", "gift_kind", "sent", "uplift", "ab"]
    readonly_fields = ["goal", "template_text", "template_text_b", "params_help"]
    fields = ["goal", "enabled", "template_id", "template_text", "template_id_b", "template_text_b", "params_help",
              "gift_kind", "gift_plugin", "gift_days", "gift_percent"]

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
        text = d.text("A")
        demo = {"NAME": "علی", "LINK": "Ab3xK9aQ", "STOP": "Ab3xK9aQ", "DB": "پایگاه من", "DAYS": "45", "AMOUNT": "490,000",
                "FEATURE": "نقشه‌ی حرارتی"}
        return format_html("<pre dir='rtl' style='white-space:pre-wrap'>{}</pre><small>حدود {} بخش پیامک؛ دامنه‌ی لینک ثابت و فقط انتهایش متغیر است (شرط sms.ir)</small>",
                           text, routes.segments(routes.render(text, demo)))

    @admin.display(description="متن قالب نسخه‌ی B (اختیاری)")
    def template_text_b(self, obj):
        d = routes.DEFS[obj.key]
        if not d.variant_b:
            return "—"
        return format_html("<pre dir='rtl' style='white-space:pre-wrap'>{}</pre>", d.text("B"))

    @admin.display(description="آزمون A/B")
    def ab(self, obj):
        r = services.ab_results(obj.key)
        if r is None:
            return "—"
        a, b = r["A"], r["B"]
        txt = f"A: {a['returned']}/{a['n']} — B: {b['returned']}/{b['n']}"
        return f"{txt} ← برنده {r['winner']}" if r["winner"] else f"{txt} (هنوز برنده‌ای نیست)"

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
    change_list_template = "admin/winback/batch_changelist.html"

    def get_urls(self):
        from django.urls import path

        return [path("manual/", self.admin_site.admin_view(self.manual_view), name="winback_manual"), *super().get_urls()]

    def manual_view(self, request):
        """ارسال دستی: انتخاب مسیر/مخاطب ← پیش‌نمایش (تعداد، هزینه، نمونه) ← تأیید تازه و زمان‌بندی."""
        from django.template.response import TemplateResponse

        if not self.has_view_permission(request):
            raise PermissionDenied
        services.sync_routes()
        rows = [r for r in Route.objects.all() if r.key in routes.DEFS]
        ctx = {**self.admin_site.each_context(request), "title": "ارسال دستی", "routes": rows, "defs": routes.DEFS,
               "switch_on": services.switch_on(), "opts": self.model._meta, "form": {}}
        if request.method == "POST":
            route = Route.objects.filter(key=request.POST.get("route", "")).first()
            d = routes.DEFS.get(route.key) if route else None
            try:
                limit = min(max(int(request.POST.get("limit") or 200), 1), 2000)
            except ValueError:
                limit = 200
            fixed = {}
            if d and d.extra_input:
                val = (request.POST.get("extra") or "").strip()[:25]
                if not val:
                    messages.error(request, "متن پارامتر الزامی است.")
                    route = None
                fixed[d.extra_input] = val
            ctx["form"] = {"route": route.key if route else request.POST.get("route", ""), "limit": limit,
                           "extra": fixed.get(d.extra_input, "") if d else ""}
            if route is None or d is None:
                pass
            elif not route.template_id or not route.enabled:
                messages.error(request, "این مسیر باید قالب داشته باشد و روشن باشد.")
            elif request.POST.get("do") == "send":
                if not stepup.ok(request):
                    return redirect(stepup.url(request))
                batch, n = services.manual_send(route, fixed, limit, request.user)
                if batch is None:
                    messages.warning(request, "گیرنده‌ی مجازی پیدا نشد.")
                else:
                    messages.success(request, f"{n} پیام زمان‌بندی شد؛ هر کدام در بهترین ساعت کاربرش می‌رود.")
                    return redirect("admin:winback_batch_changelist")
            else:
                ctx["est"] = services.manual_estimate(route, fixed, limit)
        return TemplateResponse(request, "admin/winback/manual.html", ctx)

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


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ["referrer", "referred", "created_at", "rewarded_at", "note"]
    list_filter = ["rewarded_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
