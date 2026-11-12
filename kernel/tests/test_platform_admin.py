"""تنظیم سکو از پنل: کلید ناشر (کلید عمومی)، تنظیم runner، توکن خودکار."""
import base64
import tempfile
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from kernel import pkg, platform
from kernel.models import PlatformSetting, PublisherKey
from kernel.runner import client, server


def _pub():
    k = Ed25519PrivateKey.generate()
    return base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


class PlatformTests(TestCase):
    def setUp(self):
        self.addCleanup(platform.invalidate)
        platform.invalidate()

    def test_db_overrides_settings(self):
        with override_settings(PLUGIN_RUNNER_MODE="local"):
            self.assertEqual(platform.runner_mode(), "local")
            platform.set_("runner_mode", "remote")
            self.assertEqual(platform.runner_mode(), "remote")
            self.assertEqual(client.mode(), "remote")

    def test_panel_remote_gets_default_urls(self):
        with override_settings(PLUGIN_RUNNER_URL="", PLUGIN_RUNNER_CALLBACK=""):
            platform.set_("runner_mode", "remote")
            self.assertEqual(platform.runner_url(), platform.DEFAULT_URL)
            self.assertEqual(platform.runner_callback(), platform.DEFAULT_CALLBACK)

    def test_unknown_key_rejected(self):
        with self.assertRaises(KeyError):
            platform.set_("nope", "x")

    def test_token_from_file(self):
        f = Path(tempfile.mkdtemp()) / "t"
        f.write_text("abc\n")
        with override_settings(PLUGIN_RUNNER_TOKEN=""), mock.patch.object(platform, "TOKEN_FILE", str(f)):
            self.assertEqual(platform.runner_token(), "abc")
        with override_settings(PLUGIN_RUNNER_TOKEN="env"):
            self.assertEqual(platform.runner_token(), "env")

    def test_runner_creates_token_once(self):
        f = Path(tempfile.mkdtemp()) / "tok"
        with mock.patch.object(server, "TOKEN_FILE", str(f)), mock.patch.dict("os.environ", {"RUNNER_TOKEN": ""}):
            server.ensure_token()
            first = f.read_text()
            self.assertGreaterEqual(len(first.strip()), 40)
            server.ensure_token()
            self.assertEqual(f.read_text(), first)
            self.assertEqual(server._token(), first.strip())

    def test_panel_publisher_key_is_trusted(self):
        pub = _pub()
        PublisherKey.objects.create(name="acme", public_key=pub)
        self.assertIn("acme", pkg.publisher_keys())
        PublisherKey.objects.filter(name="acme").update(active=False)
        self.assertNotIn("acme", pkg.publisher_keys())

    def test_key_validation(self):
        self.assertTrue(platform.valid_public_key(_pub()))
        self.assertFalse(platform.valid_public_key("not-base64!"))
        self.assertFalse(platform.valid_public_key(base64.b64encode(b"short").decode()))


@override_settings(ADMIN_2FA_REQUIRED=False)
class PlatformAdminViewTests(TestCase):
    def setUp(self):
        self.addCleanup(platform.invalidate)
        User = get_user_model()
        self.su = User.objects.create_superuser("root501", "pw-12345-xyz")
        self.client.force_login(self.su)
        self.url = "/manage/kernel/publisherkey/"

    def test_page_renders(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "کلیدهای ناشر")

    def test_add_and_remove_key(self):
        pub = _pub()
        self.client.post(self.url, {"action": "add_key", "name": "acme", "public_key": pub})
        k = PublisherKey.objects.get(name="acme")
        self.assertEqual(k.added_by, self.su)
        self.client.post(self.url, {"action": "remove_key", "pk": k.pk})
        self.assertFalse(PublisherKey.objects.filter(name="acme").exists())

    def test_bad_key_or_name_rejected(self):
        self.client.post(self.url, {"action": "add_key", "name": "acme", "public_key": "zzz"})
        self.client.post(self.url, {"action": "add_key", "name": "Bad Name", "public_key": _pub()})
        self.assertEqual(PublisherKey.objects.count(), 0)

    def test_save_runner(self):
        self.client.post(self.url, {"action": "save_runner", "mode": "remote", "url": "http://plugin-runner:8090",
                                    "callback": "http://web:8000", "timeout": "15"})
        self.assertEqual(PlatformSetting.objects.get(key="runner_mode").value, "remote")
        self.assertEqual(platform.runner_timeout(), 15.0)

    def test_runner_rejects_bad_input(self):
        for bad in ({"mode": "local"}, {"mode": "remote", "url": "ftp://x"}, {"mode": "remote", "url": "http://169.254.169.254"},
                    {"mode": "remote", "timeout": "999"}):
            self.client.post(self.url, {"action": "save_runner", **bad})
        self.assertFalse(PlatformSetting.objects.filter(key="runner_mode").exists())

    def test_non_admin_denied(self):
        u = get_user_model().objects.create_user("09120000502")
        self.client.force_login(u)
        self.assertIn(self.client.get(self.url).status_code, (302, 403))

    def test_mutation_needs_fresh_2fa(self):
        from kernel import stepup

        class Deny(stepup.Provider):
            def ok(self, request):
                return False

            def url(self, request):
                return "/fresh/"

        old = stepup._provider
        stepup.set_provider(Deny())
        self.addCleanup(lambda: setattr(stepup, "_provider", old))
        r = self.client.post(self.url, {"action": "add_key", "name": "acme", "public_key": _pub()})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/fresh/")
        self.assertEqual(PublisherKey.objects.count(), 0)
