"""زبانه‌ی «کانال‌های هشدار» پروفایل: اتصال، قطع، ترجیح و نمایش کد."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from kernel import notify
from kernel.models import NotifyAddress, NotifyPref

STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


@override_settings(STORAGES=STORAGES)
class ProfileAlertsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(phone="09120002222")
        self.client.force_login(self.user)
        self.url = reverse("accounts:profile")
        notify.save_channel("bale", enabled=True, token="1:T", bot_username="geobot")

    def test_tab_lists_active_channel_only(self):
        r = self.client.get(self.url)
        self.assertContains(r, 'id="p-alerts"')
        self.assertContains(r, 'value="notify_link"')
        self.assertNotContains(r, "تلگرام")

    def test_link_shows_code_once_then_unlink(self):
        r = self.client.post(self.url, {"action": "notify_link", "channel": "bale"})
        self.assertRedirects(r, f"{self.url}#alerts", fetch_redirect_response=False)
        page = self.client.get(self.url)
        code = NotifyAddress.objects.get(user=self.user)
        self.assertEqual(len(code.code_hash), 64)
        self.assertContains(page, "ble.ir/geobot?start=")
        self.assertNotContains(self.client.get(self.url), "ble.ir/geobot?start=")  # کد فقط یک‌بار نمایش داده می‌شود
        NotifyAddress.objects.update(chat_id="5")
        self.assertContains(self.client.get(self.url), "قطع اتصال")
        self.client.post(self.url, {"action": "notify_unlink", "channel": "bale"})
        self.assertFalse(NotifyAddress.objects.exists())

    def test_unlink_only_own_address(self):
        other = get_user_model().objects.create_user(phone="09120003333")
        NotifyAddress.objects.create(user=other, channel="bale", chat_id="9")
        self.client.post(self.url, {"action": "notify_unlink", "channel": "bale"})
        self.assertTrue(NotifyAddress.objects.filter(user=other).exists())

    def test_pref_saved_and_validated(self):
        self.client.post(self.url, {"action": "notify_pref", "quiet_from": "23", "quiet_to": "6", "fallback": "1"})
        p = NotifyPref.objects.get(user=self.user)
        self.assertEqual((p.quiet_from, p.quiet_to, p.fallback), (23, 6, True))
        self.client.post(self.url, {"action": "notify_pref", "quiet_from": "99", "quiet_to": "x"})
        p.refresh_from_db()
        self.assertEqual((p.quiet_from, p.quiet_to, p.fallback), (None, None, False))

    def test_inactive_channel_cannot_link(self):
        with mock.patch("kernel.notify.begin_link", wraps=notify.begin_link):
            self.client.post(self.url, {"action": "notify_link", "channel": "telegram"})
        self.assertFalse(NotifyAddress.objects.exists())
