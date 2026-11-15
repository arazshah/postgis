from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_start, name="login"),
    path("login/password/", views.login_password, name="login_password"),
    path("signup/email/", views.signup_email, name="signup_email"),
    path("signup/", RedirectView.as_view(pattern_name="accounts:login", query_string=True), name="signup"),
    path("verify/", views.verify, name="verify"),
    path("verify/resend/", views.resend, name="resend"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),
    path("email/confirm/<str:token>/", views.email_confirm, name="email_confirm"),
    path("email/resend/", views.email_resend, name="email_resend"),
    path("password/forgot/", views.password_forgot, name="password_forgot"),
    path("password/reset/<str:uidb64>/<str:token>/", views.password_reset, name="password_reset"),
]
