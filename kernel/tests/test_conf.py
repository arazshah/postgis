from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from kernel import conf, crypto
from kernel.models import PluginSetting, PluginState
from kernel.plugins import registry


class ConfTests(TestCase):
    def setUp(self):

        for o in [("tt", "n", "تعداد", "int", 5, (), 1, 10), ("tt", "m", "حالت", "choice", "a", (("a", "الف"), ("b", "ب")), None, None),
                  ("tt", "k", "کلید", "secret", None, (), None, None), ("tt", "f", "پرچم", "bool", False, (), None, None)]:
            conf.option(o[0], o[1], o[2], kind=o[3], default=o[4], choices=o[5], min=o[6], max=o[7])
        self.addCleanup(lambda: [registry.remove_plugin("tt")])

    def test_default_then_set(self):
        self.assertEqual(conf.get("tt", "n"), 5)
        conf.set_value("tt", "n", "7")
        self.assertEqual(conf.get("tt", "n"), 7)
        conf.set_value("tt", "n", "")  # خالی = پیش‌فرض
        self.assertEqual(conf.get("tt", "n"), 5)

    def test_validation(self):
        for bad in ("abc", "0", "11"):
            with self.assertRaises(ValueError):
                conf.set_value("tt", "n", bad)
        with self.assertRaises(ValueError):
            conf.set_value("tt", "m", "zzz")
        with self.assertRaises(KeyError):
            conf.get("tt", "nope")

    def test_secret_encrypted_and_not_cleared_by_blank(self):
        conf.set_value("tt", "k", "tok-123")
        raw = PluginSetting.objects.get(plugin_id="tt", key="k").value
        self.assertNotIn("tok-123", raw)
        self.assertEqual(crypto.decrypt(raw), "tok-123")
        self.assertEqual(conf.get("tt", "k"), "tok-123")
        conf.set_value("tt", "k", "")
        self.assertEqual(conf.get("tt", "k"), "tok-123")

    def test_corrupt_value_falls_back_to_default(self):
        PluginSetting.objects.create(plugin_id="tt", key="n", value="xyz")
        self.assertEqual(conf.get("tt", "n"), 5)

    def test_bool(self):
        conf.set_value("tt", "f", True)
        self.assertTrue(conf.get("tt", "f"))
        conf.set_value("tt", "f", False)
        self.assertFalse(conf.get("tt", "f"))

    def test_bad_declaration(self):
        with self.assertRaises(ValueError):
            conf.option("tt", "x", "x", kind="weird")
        with self.assertRaises(ValueError):
            conf.option("tt", "x", "x", kind="choice")


@override_settings(ADMIN_2FA_REQUIRED=False)
class ConfAdminTests(TestCase):
    def setUp(self):
        conf.option("tt", "n", "تعداد", kind="int", default=5, min=1, max=10)
        conf.option("tt", "k", "کلید", kind="secret")
        self.addCleanup(lambda: registry.remove_plugin("tt"))
        self.admin = get_user_model().objects.create_admin("root", "Str0ng-Admin-Pass")
        self.client.force_login(self.admin)
        self.st = PluginState.objects.create(plugin_id="tt")

    def test_form_roundtrip_and_secret_never_rendered(self):
        url = f"/manage/kernel/pluginstate/{self.st.pk}/options/"
        r = self.client.post(url, {"n": "8", "k": "sekret-value"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(conf.get("tt", "n"), 8)
        page = self.client.get(url)
        self.assertNotContains(page, "sekret-value")
        self.assertContains(page, "تنظیم شده")

    def test_invalid_value_rejected(self):
        r = self.client.post(f"/manage/kernel/pluginstate/{self.st.pk}/options/", {"n": "99"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(conf.get("tt", "n"), 5)
