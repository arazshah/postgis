from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_start, name="login"),
    path("signup/", RedirectView.as_view(pattern_name="accounts:login", query_string=True), name="signup"),
    path("verify/", views.verify, name="verify"),
    path("verify/resend/", views.resend, name="resend"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),
]
