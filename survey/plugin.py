"""مانیفست پلاگین «برداشت میدانی» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import nav, plugins
from kernel import settings as site_settings

plugin = plugins.register("survey", "برداشت میدانی", kind="feature", requires=("databases",))

nav.ws_section("share", "برداشت میدانی", "survey:index", "target", "viewer", plugin=plugin.id, order=30, views=("survey:index", "survey:studio"), visible="survey.plugin.enabled")
nav.home_action("data", "برداشت میدانی", "با GPS یا گیرنده RTK در میدان نقطه برداشت کن؛ آفلاین هم کار می‌کند",
                "survey:index", "target", plugin=plugin.id, order=40, visible="survey.plugin.enabled")
nav.admin_item("publish", "survey.surveyproject", None, plugin=plugin.id, order=60)
nav.admin_item("publish", "survey.gnssdriver", None, plugin=plugin.id, order=70)
nav.admin_item("publish", "survey.ntripprofile", None, plugin=plugin.id, order=80)

site_settings.section("survey", "map", "برداشت میدانی", plugin=plugin.id, order=130,
                      fields=("survey_enabled",),
                      description="نقشه‌برداری و اتصال گیرنده GNSS. تا خاموش است هیچ‌چیز برای کاربران دیده نمی‌شود.")


def enabled() -> bool:
    """برداشت میدانی با کلید تنظیمات سایت روشن و خاموش می‌شود."""
    from core.models import SiteSettings

    return bool(SiteSettings.get().survey_enabled)
