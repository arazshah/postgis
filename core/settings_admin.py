"""وضعیت زبانه‌های خود «سایت» در صفحه‌ی تنظیمات پنل مدیریت؛ در plugin.py ثبت می‌شود."""


def users_status(obj):
    return ("ok", "") if obj.signup_open and obj.allow_new_databases else ("warn", "محدود")


def track_status(obj):
    if obj.enamad_meta_content and obj.enamad_badge_html.strip():
        return ("ok", "اینماد ثبت شده")
    return ("warn", "اینماد ناقص")
