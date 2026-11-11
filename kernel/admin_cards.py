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
