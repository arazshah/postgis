from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("manage/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("dashboard/", include("databases.urls")),
    path("", include("core.urls")),
]
