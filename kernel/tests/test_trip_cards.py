"""کارت داشبورد برای قطع‌های خودکار پلاگین و علامت «دیده‌شده»."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from kernel import admin_cards, dash
from kernel.models import PluginTrip
from kernel.plugins import registry


def trip(plugin="compute", version="2.0.0", action="rollback", restored="1.0.0", **kw):
    return PluginTrip.objects.create(plugin_id=plugin, version=version, action=action, restored_version=restored, runs=40, errors=30, **kw)


class CardTests(TestCase):
    def test_no_trips_no_card(self):
        self.assertEqual(admin_cards.attention(), [])

    def test_rollback_is_warning_and_disable_is_bad(self):
        trip()
        trip(plugin="fleet", version="1.0.0", action="disable", restored="")
        items = admin_cards.attention()
        levels = {i["text"].split()[1]: i["level"] for i in items}
        self.assertEqual(levels, {"fleet": "bad", "compute": "warn"})
        self.assertIn("به نسخه‌ی 1.0.0 برگشت", [i for i in items if "compute" in i["text"]][0]["text"])
        self.assertIn("خاموش شد", [i for i in items if "fleet" in i["text"]][0]["text"])
        self.assertIn("seen=no", items[0]["url"])

    def test_more_than_three_are_summarised_and_seen_ones_are_hidden(self):
        from django.utils import timezone

        for i in range(5):
            trip(plugin=f"p{i}")
        items = admin_cards.attention()
        self.assertEqual((len(items), items[-1]["level"]), (4, "info"))
        self.assertIn("2 قطع خودکار دیگر", items[-1]["text"])
        PluginTrip.objects.update(seen_at=timezone.now())
        self.assertEqual(admin_cards.attention(), [])

    def test_registered_with_the_dashboard(self):
        self.assertIn("kernel.admin_cards.attention", [c.value for c in registry.contributions(dash.ATTENTION)])
        trip()
        self.assertTrue(any("compute" in i["text"] for i in dash.collect(dash.ATTENTION)))


@override_settings(ADMIN_2FA_REQUIRED=False)
class AdminTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_admin("root", "Str0ng-Admin-Pass")
        self.client.force_login(self.admin)

    def test_dashboard_shows_the_card_and_mark_seen_clears_it(self):
        t = trip()
        r = self.client.get("/manage/")
        self.assertContains(r, "به‌خاطر خطای پیاپی")
        r = self.client.post("/manage/kernel/plugintrip/", {"action": "mark_seen", "_selected_action": [t.pk]}, follow=True)
        self.assertContains(r, "دیده‌شده شد")
        t.refresh_from_db()
        self.assertIsNotNone(t.seen_at)
        self.assertNotContains(self.client.get("/manage/"), "به‌خاطر خطای پیاپی")

    def test_filter_and_readonly(self):
        a, b = trip(), trip(plugin="other")
        PluginTrip.objects.filter(pk=b.pk).update(seen_at=a.tripped_at)
        r = self.client.get("/manage/kernel/plugintrip/?seen=no")
        self.assertEqual([x.plugin_id for x in r.context["cl"].result_list], ["compute"])
        self.assertEqual(self.client.get(f"/manage/kernel/plugintrip/{a.pk}/delete/").status_code, 403)
        self.assertEqual(self.client.get("/manage/kernel/plugintrip/add/").status_code, 403)
