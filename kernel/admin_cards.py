"""کارت «نیاز به توجه» داشبورد مدیر برای قطع‌های خودکار پلاگین (kernel.health)؛ تا وقتی مدیر «دیده‌شده» نزند می‌ماند."""
from . import dash
from .models import PluginTrip


def attention():
    trips = list(PluginTrip.objects.filter(seen_at__isnull=True).order_by("-tripped_at")[:50])
    if not trips:
        return []
    out = []
    for t in trips[:3]:
        what = f"به نسخه‌ی {t.restored_version} برگشت" if t.action == PluginTrip.Action.ROLLBACK else "خاموش شد"
        out.append(dash.item("bad" if t.action == PluginTrip.Action.DISABLE else "warn",
                             f"پلاگین {t.plugin_id} نسخه‌ی {t.version} به‌خاطر خطای پیاپی {what} ({t.errors} خطا از {t.runs} اجرا)",
                             "بررسی", dash.url("admin:kernel_plugintrip_changelist", "?seen=no")))
    if len(trips) > 3:
        out.append(dash.item("info", f"{len(trips) - 3} قطع خودکار دیگر هم دیده نشده است", "همه", dash.url("admin:kernel_plugintrip_changelist", "?seen=no")))
    return out


def ext_state():
    """کارت پلاگین سطح ۳: حالت امن، پلاگین‌های کنارگذاشته‌ی پیش‌پرواز شروع یا خاموش‌شده با PLUGINS_DISABLED."""
    from django.conf import settings

    from . import extpreflight

    link = dash.url("admin:kernel_pluginstate_changelist")
    out = []
    mark = extpreflight.read_marker()
    if getattr(settings, "PLUGINS_SAFE_MODE", False):
        out.append(dash.item("warn", "حالت امن روشن است: هیچ پلاگین سطح ۳ بار نشده (PLUGINS_SAFE_MODE=1)", "پلاگین‌ها", link))
    elif mark.get("safe_mode"):
        out.append(dash.item("bad", f"سایت در حالت امن بالا آمد؛ هیچ پلاگین سطح ۳ بار نشد. {mark.get('reason', '')}".strip(), "پلاگین‌ها", link))
    for pid, why in sorted((mark.get("disabled") or {}).items()):
        out.append(dash.item("bad", f"پلاگین سطح ۳ «{pid}» در شروع کنار گذاشته شد ({why})", "پلاگین‌ها", link))
    manual = [x.strip() for x in str(getattr(settings, "PLUGINS_DISABLED", "")).split(",") if x.strip()]
    if manual:
        out.append(dash.item("info", f"با PLUGINS_DISABLED خاموش‌اند: {'، '.join(manual)}", "پلاگین‌ها", link))
    return out
