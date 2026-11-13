"""قیف بازارچه پلاگین: رویدادهای فهرست/جزئیات/ورود/آزمایشی/خرید و گزارش آن (ADR-0011)."""
from django.test import TestCase
from django.urls import reverse

from analytics import reports
from analytics.models import Event

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"


class MarketFunnelTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_USER_AGENT"] = UA

    def test_list_detail_and_login_click_are_recorded_and_reported(self):
        self.client.get(reverse("plugins"))  # بازدید اول: فقط کوکی می‌گیرد
        self.client.get(reverse("plugins"))
        self.client.get(reverse("plugin_detail", args=["dbimport"]))
        self.client.get(reverse("accounts:login") + "?next=/plugins/dbimport/")
        names = list(Event.objects.values_list("name", flat=True))
        for n in (Event.MARKET_LIST, Event.MARKET_DETAIL, Event.MARKET_CTA):
            self.assertIn(n, names)
        self.assertEqual(Event.objects.get(name=Event.MARKET_DETAIL).meta["plugin"], "dbimport")
        self.assertEqual(Event.objects.get(name=Event.MARKET_CTA).meta["plugin"], "dbimport")
        rep = reports.market_funnel(30)
        self.assertEqual([s["n"] for s in rep["steps"]][:3], [1, 1, 1])
        self.assertEqual(rep["plugins"][0]["plugin"], "dbimport")

    def test_do_not_track_records_nothing(self):
        self.client.get(reverse("plugins"))
        before = Event.objects.count()
        self.client.get(reverse("plugin_detail", args=["dbimport"]), HTTP_DNT="1")
        self.assertEqual(Event.objects.count(), before)

    def test_admin_report_shows_market_funnel(self):
        from accounts.models import User

        admin = User.objects.create_user(email="boss@example.com", password="x", is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        with self.settings(ADMIN_2FA_REQUIRED=False):
            r = self.client.get(reverse("admin:analytics_sourcereport_changelist"))
        self.assertContains(r, "قیف بازارچه پلاگین")
