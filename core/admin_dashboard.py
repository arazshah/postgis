"""داده‌ی داشبورد پنل مدیریت: نیاز به توجه، سلامت سیستم، آمار کلیدی با روند و فعالیت اخیر.

هر ردیف را پلاگین صاحبش ثبت می‌کند (kernel.admin)؛ اینجا فقط کنار هم گذاشته می‌شوند.
"""
from django.urls import reverse

from kernel import admin as dash

from . import admin_nav


def build():
    act = dash.collect(dash.ACTIVITY)
    act.sort(key=lambda r: r["at"], reverse=True)
    quick = [{"label": a, "icon": i, "url": reverse(n)} for a, i, n in admin_nav.QUICK]
    return {"ap_attention": dash.collect(dash.ATTENTION), "ap_health": dash.collect(dash.HEALTH),
            "ap_kpis": dash.collect(dash.KPI), "ap_activity": act[:8], "ap_quick": quick}
