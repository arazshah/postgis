from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import FaPasswordChangeForm, LoginForm, ProfileForm, SignupForm


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("databases:dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "حساب شما ساخته شد. حالا اولین پایگاه داده مکانی خود را بسازید.")
        return redirect("databases:create")
    return render(request, "accounts/signup.html", {"form": form})


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user, prefix="p")
    pform = FaPasswordChangeForm(request.user, request.POST or None, prefix="pw")
    if request.method == "POST":
        if "save_profile" in request.POST and form.is_valid():
            form.save()
            messages.success(request, "اطلاعات حساب ذخیره شد.")
            return redirect("accounts:profile")
        if "change_password" in request.POST and pform.is_valid():
            user = pform.save()
            update_session_auth_hash(request, user)
            messages.success(request, "رمز عبور حساب تغییر کرد.")
            return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form, "pform": pform})
