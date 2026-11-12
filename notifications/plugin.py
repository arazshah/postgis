"""مانیفست پلاگین «اعلان‌ها» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import plugins

plugin = plugins.register("notifications", "اعلان‌ها", kind="system", requires=("jobs",))

from kernel import profile as profile_sections  # noqa: E402

profile_sections.section("alerts", "کانال‌های هشدار", "notifications/_profile_alerts.html", plugin=plugin.id, order=20,
                         context="notifications.profile.context", badge="notifications.profile.has_channel",
                         actions=("notify_link", "notify_unlink", "notify_pref"), handle="notifications.profile.handle",
                         badge_title="متصل")
