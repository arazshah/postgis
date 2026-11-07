"""دریافت درخواست از سایت pgpro.ir (پایگاه داده مکانی پرو): پیش‌فاکتور، پیش‌فروش و نسخه‌ی آزمایشی.

سایت استاتیک است؛ فرمش با fetch به همین نقطه می‌فرستد. درخواست همان سرنخ «درخواست تماس» پنل است
(موضوع «pgpro») و در پنل مدیریت و اعلان مدیر دیده می‌شود. ورودی فقط از مبدأهای سایت پذیرفته می‌شود.
"""
from django.conf import settings
from django.http import HttpResponse, JsonResponse

from . import contact as contact_svc

INTERESTS = {"quote": "درخواست پیش‌فاکتور", "preorder": "پیش‌فروش", "trial": "نسخه‌ی آزمایشی", "info": "اطلاعات بیشتر"}
FORM_ERROR = "ثبت درخواست ناموفق بود؛ موارد مشخص‌شده را اصلاح کنید."


def cors(request, response):
    origin = request.headers.get("Origin", "")
    if origin and origin in getattr(settings, "PGPRO_SITE_ORIGINS", []):
        response["Access-Control-Allow-Origin"] = origin
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        response["Access-Control-Max-Age"] = "86400"
        response["Vary"] = "Origin"
    return response


def _message(post) -> str:
    interest = INTERESTS.get(post.get("interest", ""), INTERESTS["info"])
    lines = [f"درخواست از pgpro.ir · {interest}"]
    qty = (post.get("quantity") or "").strip()[:20]
    if qty:
        lines.append(f"تعداد دستگاه: {qty}")
    use = (post.get("usage") or "").strip()[:40]
    if use:
        lines.append(f"زمینه‌ی کار: {use}")
    text = (post.get("message") or "").strip()[:1500]
    if text:
        lines.append(text)
    return "\n".join(lines)


def handle(request):
    from accounts.otp import client_ip

    if request.method == "OPTIONS":
        return cors(request, HttpResponse(status=204))
    origin = request.headers.get("Origin", "")
    if origin and origin not in getattr(settings, "PGPRO_SITE_ORIGINS", []):
        return JsonResponse({"ok": False, "error": "مبدأ مجاز نیست."}, status=403)
    data = request.POST.copy()
    data["topic"] = "pgpro"
    data["message"] = _message(request.POST)
    form = contact_svc.ContactForm(data)
    ip = client_ip(request)
    limit = contact_svc.throttled(ip)
    if not limit and form.is_valid():
        limit = contact_svc.throttled(ip, form.cleaned_data["phone"])
        if not limit:
            contact_svc.submit(form, None, ip)
            return cors(request, JsonResponse({"ok": True}))
    if limit:
        return cors(request, JsonResponse({"ok": False, "error": limit}, status=429))
    errors = {k: v[0] for k, v in form.errors.items() if k != "__all__"}
    return cors(request, JsonResponse({"ok": False, "error": FORM_ERROR, "errors": errors}, status=400))
