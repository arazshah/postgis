from django.contrib import admin
from django.urls import include, path

from accounts.admin_auth import LockoutAdminAuthenticationForm

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
    path("manage/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("dashboard/", include("databases.urls")),
    path("billing/", include("billing.urls")),
    path("support/", include("support.urls")),
    path("", include("core.urls")),
]
