from django.contrib import admin
from django.http import Http404
from django.urls import include, path

from accounts.admin_2fa import twofa as admin_2fa
from accounts.admin_auth import LockoutAdminAuthenticationForm
from billing import views as billing_views
from core.admin_search import search as admin_search
from kernel import geocode_admin as kernel_geocode_admin
from kernel import hub as kernel_hub
from kernel import routes as kernel_routes


def _r_short(request, code):
    """`/r/<کد>/` دو کاربرد دارد: لینک کوتاه پیامک بازگشت (winback؛ قالب لینک پیامک ثابت است) و نمای رستر
    (`enterprise:raster_view`). الگوی فراگیر winback قبلاً نمای رستر را می‌پوشاند (۴۰۴)؛ اول کد پیامک امتحان می‌شود،
    اگر کد پیامکی نبود، رستر."""
    from enterprise import views as enterprise_views
    from winback import views as winback_views

    try:
        return winback_views.go(request, code)
    except Http404:
        return enterprise_views.raster_view(request, code)


# پنل مدیریت جدا از حساب کاربران: ورود با نام کاربری و رمز عبور
admin.site.login_form = LockoutAdminAuthenticationForm
admin.site.site_header = "پنل مدیریت"
admin.site.site_title = "پنل مدیریت"
admin.site.index_title = "داشبورد"

_original_index = admin.site.index


def _index_with_stats(request, extra_context=None):
    from core.admin_dashboard import build

    return _original_index(request, {**build(), **(extra_context or {})})


admin.site.index = _index_with_stats

urlpatterns = [
    path("live/", include("live.urls")),
    path("manage/2fa/", admin_2fa, name="admin_2fa"),
    path("manage/plugins/", kernel_hub.hub, name="plugin_hub"),
    path("manage/plugins/sample/", kernel_hub.install_sample, name="plugin_sample"),
    path("manage/geocode-lab/", kernel_geocode_admin.lab, name="geocode_lab"),
    path("manage/_search/", admin.site.admin_view(admin_search), name="admin_search"),
    path("manage/", admin.site.urls),
    path("plugins/", billing_views.market, name="plugins"),
    path("plugins/for/<slug:aud>/", billing_views.market_audience, name="plugin_audience"),
    path("plugins/<slug:plugin_id>/", billing_views.market_detail, name="plugin_detail"),
    path("accounts/", include("accounts.urls")),
    path("dashboard/", include("databases.urls")),
    path("billing/", include("billing.urls")),
    path("support/", include("support.urls")),
    path("class/", include("classroom.urls")),
    path("go/", include("analytics.urls")),
    path("r/<str:code>/", _r_short, name="r_short"),       # پیش از winback.urls: فقط مسیر تک‌بخشی را می‌گیرد
    path("r/", include("winback.urls")),
    path("assistant/", include("assistant.urls")),
    path("", include("kb.urls")),
    path("", include("publish.urls")),
    path("", include("maps.urls")),
    path("", include("survey.urls")),
    path("", include("iranmap.urls")),
    path("", include("analysis.urls")),
    path("", include("tools.urls")),
    path("", include("notifications.urls")),
    path("", include("restapi.urls")),
    path("", include("enterprise.urls")),
    path("", include("satellite.urls")),
    path("", include("kernel.urls")),
    # پلاگین‌های سطح ۳ (ext/): فقط زیر /x/ و dashboard/<pk>/x/ (docs/adr/0007)
    path("x/", include((kernel_routes.patterns("ext"), "ext"))),
    path("dashboard/<int:pk>/x/", include((kernel_routes.patterns("ws_ext"), "ws_ext"))),
    path("", include("core.urls")),
]
