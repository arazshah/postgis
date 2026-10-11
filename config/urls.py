from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    # ورود به پنل مدیریت هم با موبایل و رمز یک‌بار مصرف انجام می‌شود
    path("manage/login/", RedirectView.as_view(url="/accounts/login/?next=/manage/", permanent=False)),
    path("manage/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("dashboard/", include("databases.urls")),
    path("", include("core.urls")),
]
