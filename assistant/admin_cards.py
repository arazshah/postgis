"""سهم «دستیار هوشمند» در داشبورد پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from kernel import admin as dash


def health():
    from core.models import SiteSettings

    from .settings_admin import tab_status

    return [dash.health_item("دستیار", *tab_status(SiteSettings.get()),
                             dash.url("admin:core_sitesettings_changelist") + "#assistant", "spark")]
