from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def site_user_required(view):
    """صفحه‌های کاربری فقط برای کاربران سایت؛ حساب مدیر به پنل مدیریت هدایت می‌شود."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.user.is_staff:
            messages.info(request, "حساب مدیریتی برای پنل کاربران نیست. برای تست، با موبایل یک حساب کاربری جدا بسازید.")
            return redirect("admin:index")
        return view(request, *args, **kwargs)

    return wrapper
