"""جست‌وجوی سراسری رکوردها در پنل مدیریت (Ctrl+K): هر پلاگین جست‌وجوی مدل‌های خودش را ثبت می‌کند (kernel.dash)."""
from django.http import JsonResponse

from kernel import dash as dash


def search(request):
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2 or not request.user.is_staff:
        return JsonResponse({"rows": []})
    return JsonResponse({"rows": dash.collect(dash.SEARCH, request, q)})
