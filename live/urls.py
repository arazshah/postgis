from django.urls import include, path

from . import auth, sso, views

app_name = "live"
urlpatterns = [
    path("", include("live.workflow_urls")),
    path("auth/password/reset/<str:uidb64>/<str:token>/", auth.flow, {"step": "reset"}, name="auth_password_reset"),
    path("auth/email/confirm/<str:token>/", auth.flow, {"step": "confirm"}, name="auth_email_confirm"),
    path("auth/<str:step>/", auth.flow, name="auth"),
    path("launch/<int:pk>/", sso.launch, name="launch"),
    path("exchange/", sso.exchange, name="exchange"),
    path("leave/", sso.leave, name="leave"),
    path("", views.index, name="index"),
    path("<int:pk>/", views.projects, name="projects"),
    path("<int:pk>/<int:map_id>/", views.studio, name="studio"),
    path("<int:pk>/table/", views.table, name="table"),
    path("<int:pk>/tool/", views.tool, name="tool"),
    path("<int:pk>/tool/<int:job_id>/", views.tool_status, name="tool_status"),
]
