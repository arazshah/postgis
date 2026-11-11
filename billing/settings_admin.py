"""بخش «پرداخت» صفحه‌ی تنظیمات پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from django.contrib import messages
from django.urls import reverse
from django.utils.html import format_html


def tab_status(obj):
    if not obj.pay_gateway_enabled:
        return ("warn", "غیرفعال")
    if obj.gateway_sandbox:
        return ("warn", "آزمایشی")
    return ("ok", "فعال") if obj.gateway_merchant_encrypted else ("bad", "مرچنت وارد نشده")


def gateway_status(obj):
    if obj.gateway_merchant_encrypted:
        return format_html('<b style="color:#1a7f4b">ذخیره شده</b>')
    if obj.gateway_sandbox:
        return format_html('<b style="color:#b54708">وارد نشده — فقط حالت آزمایشی کار می‌کند</b>')
    return format_html('<b style="color:#b42318">وارد نشده</b>')


def gateway_tools(obj):
    return format_html('<a class="button" href="{}">آزمایش اتصال به درگاه</a>',
                       reverse("admin:core_sitesettings_gatewaytest"))


def gateway_test_view(request, model_admin):
    """یک درخواست پرداخت ۱۰ هزار تومانی می‌سازد (بدون پرداخت) تا مرچنت و دسترسی سرور به درگاه بررسی شود."""
    from .gateways import GatewayError, get_gateway

    conf = model_admin.model.get()
    try:
        gw = get_gateway(conf)
        res = gw.request(amount_rial=100000, callback_url=request.build_absolute_uri("/billing/invoices/"),
                         description="آزمایش اتصال از پنل مدیریت", order_id="TEST")
    except GatewayError as exc:
        messages.error(request, f"آزمایش درگاه ناموفق بود: {exc}")
    else:
        mode = " (حالت آزمایشی)" if conf.gateway_sandbox else ""
        messages.success(request, format_html(
            "اتصال به {}{} درست است. <a href=\"{}\" target=\"_blank\">صفحه پرداخت آزمایشی</a> "
            "(پرداخت نکنید).", gw.title, mode, res.pay_url))
