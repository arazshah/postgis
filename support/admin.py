from django import forms
from django.contrib import admin, messages
from django.db.models import Case, Count, IntegerField, Value, When
from django.template.defaultfilters import linebreaksbr
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from core.templatetags.fa import jdatetime_full

from . import services
from .forms import clean_attachment
from .models import Ticket


class TicketAdminForm(forms.ModelForm):
    reply = forms.CharField(label="پاسخ شما", required=False, widget=forms.Textarea(attrs={"rows": 8, "cols": 90}),
                            help_text="با ذخیره، پاسخ برای کاربر ثبت و پیامک اطلاع‌رسانی ارسال می‌شود.")
    reply_attachment = forms.FileField(label="پیوست پاسخ", required=False)
    close_after = forms.BooleanField(label="بعد از پاسخ، تیکت بسته شود", required=False)

    class Meta:
        model = Ticket
        fields = ["status", "category"]

    def clean_reply_attachment(self):
        return clean_attachment(self.cleaned_data.get("reply_attachment"))


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    form = TicketAdminForm
    list_display = ["number", "subject", "user", "category", "status_col", "msg_count", "updated_at"]
    list_filter = ["status", "category"]
    search_fields = ["number", "subject", "user__phone", "user__full_name", "messages__body"]
    readonly_fields = ["number", "user_link", "subject", "database", "plan", "created_at", "updated_at", "thread"]
    fieldsets = (
        (None, {"fields": ("number", "user_link", "subject", "category", "status", "database", "plan",
                           "created_at", "updated_at")}),
        ("گفتگو", {"fields": ("thread",)}),
        ("پاسخ", {"fields": ("reply", "reply_attachment", "close_after")}),
    )
    actions = ["close_selected"]

    def get_queryset(self, request):
        prio = Case(When(status=Ticket.Status.OPEN, then=Value(0)), When(status=Ticket.Status.ANSWERED, then=Value(1)),
                    default=Value(2), output_field=IntegerField())
        return (super().get_queryset(request).select_related("user")
                .annotate(_msgs=Count("messages", distinct=True), _prio=prio).order_by("_prio", "-updated_at"))

    def get_ordering(self, request):
        return []  # ترتیب از get_queryset: اول منتظر پاسخ‌ها

    def has_add_permission(self, request):
        return False

    @admin.display(description="کاربر")
    def user_link(self, t):
        url = reverse("admin:accounts_siteuser_change", args=[t.user_id])
        return format_html('<a href="{}">{}</a> {}', url, t.user.phone or t.user, t.user.full_name or "")

    @admin.display(description="پیام‌ها")
    def thread(self, t):
        rows = []
        for m in t.messages.select_related("author"):
            who = f"پشتیبانی ({m.author})" if m.is_staff else "کاربر"
            bg = "#D7EEDF" if m.is_staff else "#F4F6F4"
            file = (format_html(' · <a href="{}">پیوست: {}</a>', reverse("support:attachment", args=[m.pk]),
                                m.attachment_name) if m.attachment else "")
            rows.append(format_html(
                '<div style="background:{};border-radius:8px;padding:10px 14px;margin:0 0 10px;max-width:760px">'
                '<div style="font-size:.85em;color:#4B6269;margin-bottom:6px"><b>{}</b> · {}{}</div>'
                '<div style="line-height:1.9;white-space:normal">{}</div></div>',
                bg, who, jdatetime_full(m.created_at), file, linebreaksbr(m.body, autoescape=True)))
        return format_html_join("", "{}", ((r,) for r in rows)) or "—"

    @admin.display(description="پیام‌ها", ordering="_msgs")
    def msg_count(self, t):
        return t._msgs

    @admin.display(description="وضعیت", ordering="status")
    def status_col(self, t):
        colors = {"open": "#b42318", "answered": "#1a7f4b", "closed": "#4B6269"}
        return format_html('<b style="color:{}">{}</b>', colors[t.status], t.get_status_display())

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        body = (form.cleaned_data.get("reply") or "").strip()
        if body:
            services.staff_reply(obj, request.user, body, form.cleaned_data.get("reply_attachment"),
                                 close=form.cleaned_data.get("close_after", False))
            self.message_user(request, f"پاسخ تیکت {obj.number} ثبت شد و به کاربر اطلاع داده شد.", messages.SUCCESS)
        elif form.cleaned_data.get("close_after"):
            services.close(obj)

    @admin.action(description="بستن تیکت‌های انتخاب‌شده")
    def close_selected(self, request, queryset):
        for t in queryset:
            services.close(t)
        self.message_user(request, "تیکت‌ها بسته شدند.", messages.SUCCESS)
