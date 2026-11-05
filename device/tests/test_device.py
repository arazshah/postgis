"""آزمون حالت دستگاه pgpro. فقط با DJANGO_SETTINGS_MODULE=config.settings_device اجرا می‌شود
(در اجرای معمول ابری skip می‌شود): DJANGO_SETTINGS_MODULE=config.settings_device DJANGO_TESTING=1 python manage.py test device"""
import unittest
from io import StringIO

from django.conf import settings

if not getattr(settings, "DEVICE_MODE", False):  # در اجرای ابری، اپ device نصب نیست
    raise unittest.SkipTest("فقط با DJANGO_SETTINGS_MODULE=config.settings_device")

from django.core.cache import cache  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.test import TestCase  # noqa: E402

from accounts.models import User  # noqa: E402
from databases.models import DatabaseServer, Plan, UserDatabase  # noqa: E402
from device import services  # noqa: E402
from device.middleware import host_allowed  # noqa: E402
from device.models import DeviceProfile  # noqa: E402


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = services.create_user("admin", "pgpro", full_name="مدیر", admin=True, must_change=True)

    def login(self, username="admin", password="pgpro"):
        return self.client.post("/accounts/login/", {"identifier": username, "password": password})

    def login_ready(self):
        """مدیری که رمزش را عوض کرده و وارد شده."""
        services.set_password(self.admin, "Rah-Neshan-91", must_change=False)
        self.assertEqual(self.login(password="Rah-Neshan-91").status_code, 302)


class LoginTests(Base):
    def test_home_redirects_to_login(self):
        r = self.client.get("/")
        self.assertRedirects(r, "/accounts/login/", fetch_redirect_response=False)

    def test_login_page_renders(self):
        r = self.client.get("/accounts/login/")
        self.assertContains(r, "نام کاربری یا موبایل")
        self.assertNotContains(r, "پیامک")

    def test_default_login_forces_password_change(self):
        self.assertEqual(self.login().status_code, 302)
        r = self.client.get("/dashboard/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/device/password/"))
        # نمایش صفحه‌ی تغییر رمز و خروج آزاد است
        self.assertContains(self.client.get("/device/password/"), "رمز تازه بگذارید")

    def test_change_password_unlocks_site(self):
        self.login()
        r = self.client.post("/device/password/", {"old": "pgpro", "new1": "Rah-Neshan-91", "new2": "Rah-Neshan-91"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get("/dashboard/").status_code, 200)
        self.assertFalse(DeviceProfile.objects.get(user=self.admin).must_change_password)

    def test_password_rules(self):
        self.login()
        for new in ("pgpro", "12345678", "short1"):
            r = self.client.post("/device/password/", {"old": "pgpro", "new1": new, "new2": new})
            self.assertEqual(r.status_code, 200, new)
            self.assertContains(r, "errorlist")
        r = self.client.post("/device/password/", {"old": "نادرست", "new1": "Rah-Neshan-91", "new2": "Rah-Neshan-91"})
        self.assertContains(r, "رمز فعلی درست نیست")
        r = self.client.post("/device/password/", {"old": "pgpro", "new1": "Rah-Neshan-91", "new2": "Rah-Neshan-92"})
        self.assertContains(r, "یکی نیست")

    def test_wrong_password_and_unknown_user(self):
        for ident in ("admin", "nobody"):
            r = self.login(ident, "bad")
            self.assertContains(r, "درست نیست")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_lockout_after_failures(self):
        for _ in range(services.MAX_FAILS):
            self.login("admin", "bad")
        r = self.login("admin", "pgpro")  # رمز درست هم رد می‌شود
        self.assertContains(r, "قفل شد")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_by_phone(self):
        services.create_user("sara", "Rah-Neshan-91", phone="۰۹۱۲۱۲۳۴۵۶۷", must_change=False)
        self.assertEqual(self.login("09121234567", "Rah-Neshan-91").status_code, 302)
        self.assertEqual(self.client.get("/dashboard/").status_code, 200)

    def test_inactive_user_cannot_login(self):
        u = services.create_user("sara", "Rah-Neshan-91", phone="09121234567", must_change=False)
        u.is_active = False
        u.save()
        self.assertContains(self.login("sara", "Rah-Neshan-91"), "درست نیست")

    def test_next_is_safe(self):
        services.set_password(self.admin, "Rah-Neshan-91", must_change=False)
        r = self.client.post("/accounts/login/?next=https://evil.example/x",
                             {"identifier": "admin", "password": "Rah-Neshan-91"})
        self.assertNotIn("evil.example", r["Location"])

    def test_otp_routes_redirect(self):
        self.assertRedirects(self.client.get("/accounts/verify/"), "/accounts/login/", fetch_redirect_response=False)


class GuardTests(Base):
    def test_host_validation(self):
        for host, ok in [("pgpro.local", True), ("pgpro", True), ("192.168.1.20", True), ("192.168.1.20:80", True),
                         ("[::1]:8000", True), ("localhost", True), ("evil.example.com", False), ("", False)]:
            self.assertEqual(host_allowed(host), ok, host)
        self.assertEqual(self.client.get("/accounts/login/", HTTP_HOST="evil.example.com").status_code, 400)
        self.assertEqual(self.client.get("/accounts/login/", HTTP_HOST="pgpro.local").status_code, 200)

    def test_cloud_sections_are_gone(self):
        for path in ("/billing/plans/", "/support/", "/class/", "/assistant/config/", "/go/x/"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_healthz(self):
        self.assertEqual(self.client.get("/healthz", HTTP_HOST="127.0.0.1").status_code, 200)

    def test_cookies_not_secure(self):
        self.assertFalse(settings.SESSION_COOKIE_SECURE)
        self.assertEqual(settings.SECURE_HSTS_SECONDS, 0)

    def test_menu_has_no_cloud_links(self):
        self.login_ready()
        html = self.client.get("/dashboard/").content.decode()
        for bad in ("/billing/", "/support/", "/class/", "unpkg.com", "t.me/"):
            self.assertNotIn(bad, html, bad)
        self.assertIn("/device/users/", html)  # مدیر منوی کاربران را می‌بیند
        self.assertNotIn("/manage/", html)

    def test_manage_panel_is_closed_even_for_admin(self):
        self.login_ready()
        for path in ("/manage/", "/manage/login/", "/manage/accounts/user/"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_docs_pages_render(self):
        self.login_ready()
        for path in ("/docs/", "/docs/start/", "/help/", "/kb/"):
            self.assertEqual(self.client.get(path).status_code, 200, path)


class UsersTests(Base):
    def setUp(self):
        super().setUp()
        self.login_ready()

    def post(self, **data):
        return self.client.post("/device/users/", data)

    def test_list_renders(self):
        r = self.client.get("/device/users/")
        self.assertContains(r, "کاربران دستگاه")
        self.assertContains(r, "admin")

    def test_regular_user_forbidden(self):
        services.create_user("sara", "Rah-Neshan-91", phone="09121234567", must_change=False)
        self.client.logout()
        self.login("sara", "Rah-Neshan-91")
        self.assertEqual(self.client.get("/device/users/").status_code, 302)
        self.assertEqual(self.client.get("/device/system/").status_code, 302)
        self.assertEqual(self.client.post("/device/time/", {"epoch": "1900000000"}).status_code, 302)
        self.assertEqual(self.client.get("/manage/").status_code, 404)

    def test_create_user(self):
        r = self.post(action="create", username="Sara", full_name="سارا", phone="09121234567", password="vqx7m3kp2d",
                      role="user")
        self.assertEqual(r.status_code, 302)
        u = User.objects.get(username="sara")
        self.assertFalse(u.is_superuser)
        self.assertFalse(u.is_staff)
        self.assertTrue(u.check_password("vqx7m3kp2d"))
        self.assertTrue(u.device_profile.must_change_password)
        # ورود با رمز موقت و اجبار به تغییر رمز
        self.client.logout()
        self.login("sara", "vqx7m3kp2d")
        self.assertTrue(self.client.get("/dashboard/")["Location"].startswith("/device/password/"))

    def test_create_validation(self):
        for data in (dict(username="1ab", phone="09121234567"), dict(username="ok_user", phone="123"),
                     dict(username="ok_user", phone="09121234567", password="pgpro"),
                     dict(username="admin", phone="09121234567", password="vqx7m3kp2d")):
            r = self.post(action="create", role="user", **data)
            self.assertEqual(r.status_code, 200, data)
            self.assertContains(r, "data-open")
        self.assertEqual(User.objects.count(), 1)

    def test_create_admin_role(self):
        self.post(action="create", username="boss", phone="09121234567", password="vqx7m3kp2d", role="admin")
        self.assertTrue(User.objects.get(username="boss").is_superuser)

    def test_last_admin_protected(self):
        pk = self.admin.pk
        self.post(action="edit", user=pk, role="user", full_name="x")
        self.post(action="toggle", user=pk)
        self.post(action="delete", user=pk)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser and self.admin.is_active)

    def test_cannot_delete_or_disable_self_even_with_other_admin(self):
        other = services.create_user("boss", "vqx7m3kp2d", phone="09121234568", admin=True)
        self.post(action="toggle", user=self.admin.pk)
        self.post(action="delete", user=self.admin.pk)
        self.assertTrue(User.objects.filter(pk=self.admin.pk, is_active=True).exists())
        # ولی دیگری را می‌شود
        self.post(action="toggle", user=other.pk)
        other.refresh_from_db()
        self.assertFalse(other.is_active)

    def test_reset_password(self):
        u = services.create_user("sara", "Rah-Neshan-91", phone="09121234567", must_change=False)
        self.post(action="reset", user=u.pk, password="mn4kq8wz7t")
        u.refresh_from_db()
        self.assertTrue(u.check_password("mn4kq8wz7t"))
        self.assertTrue(u.device_profile.must_change_password)
        self.post(action="reset", user=u.pk, password="pgpro")  # رمز پیش‌فرض رد می‌شود
        u.refresh_from_db()
        self.assertTrue(u.check_password("mn4kq8wz7t"))

    def test_edit_user(self):
        u = services.create_user("sara", "Rah-Neshan-91", phone="09121234567", must_change=False)
        self.post(action="edit", user=u.pk, role="admin", full_name="سارا احمدی", organization="شهرداری",
                  phone="09129998877")
        u.refresh_from_db()
        self.assertTrue(u.is_superuser)
        self.assertEqual((u.full_name, u.organization, u.phone), ("سارا احمدی", "شهرداری", "09129998877"))

    def test_delete_user_with_database_refused(self):
        u = services.create_user("sara", "Rah-Neshan-91", phone="09121234567", must_change=False)
        srv = DatabaseServer.objects.create(name="s", host="h", public_host="h")
        plan = Plan.objects.create(name="p", slug="p")
        UserDatabase.objects.create(owner=u, server=srv, plan=plan, label="abc", db_name="gp_abc", role_name="gp_abc_user",
                                    status=UserDatabase.Status.ACTIVE)
        self.post(action="delete", user=u.pk)
        self.assertTrue(User.objects.filter(pk=u.pk).exists())
        UserDatabase.objects.all().delete()
        self.post(action="delete", user=u.pk)
        self.assertFalse(User.objects.filter(pk=u.pk).exists())

    def test_database_never_expires(self):
        srv = DatabaseServer.objects.create(name="s", host="h", public_host="h")
        plan = Plan.objects.create(name="p", slug="p")
        db = UserDatabase.objects.create(owner=self.admin, server=srv, plan=plan, label="abc", db_name="gp_abc",
                                         role_name="gp_abc_user", status=UserDatabase.Status.ACTIVE)
        db.extend(90)
        db.save()
        db.refresh_from_db()
        self.assertIsNone(db.expires_at)


class SystemTests(Base):
    def setUp(self):
        super().setUp()
        self.login_ready()

    def test_system_page(self):
        r = self.client.get("/device/system/")
        self.assertContains(r, "pgpro.local")
        self.assertContains(r, "ساعت دستگاه")

    def test_time_sync_validation(self):
        self.assertEqual(self.client.post("/device/time/", {"epoch": "abc"}).status_code, 400)
        r = self.client.post("/device/time/", {"epoch": "5"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/device/time/", {"epoch": "1900000000"})  # ابزار روی این ماشین نصب نیست
        self.assertEqual(r.status_code, 400)
        self.assertIn("ابزار", r.json()["message"])
        self.assertEqual(self.client.get("/device/time/").status_code, 405)


class InitTests(TestCase):
    def run_init(self):
        out = StringIO()
        call_command("device_init", stdout=out)
        return out.getvalue()

    def test_init_is_idempotent_and_keeps_changed_password(self):
        self.run_init()
        admin = User.objects.get(username="admin")
        self.assertTrue(admin.is_superuser and not admin.is_staff)
        self.assertTrue(admin.check_password("pgpro"))
        self.assertTrue(admin.device_profile.must_change_password)
        services.set_password(admin, "Rah-Neshan-91", must_change=False)
        self.run_init()
        admin.refresh_from_db()
        self.assertTrue(admin.check_password("Rah-Neshan-91"))
        self.assertEqual(User.objects.count(), 1)
        plan = Plan.objects.get(is_default=True)
        self.assertEqual(plan.slug, "pgpro")
        self.assertEqual(Plan.objects.filter(is_default=True).count(), 1)
        from core.models import SiteSettings
        conf = SiteSettings.get()
        self.assertFalse(conf.signup_open)
        self.assertEqual(conf.map_tile_url, "")


class ResetPasswordCommandTests(TestCase):
    def test_reset_reactivates_and_forces_change(self):
        u = services.create_user("admin", "Rah-Neshan-91", admin=True, must_change=False)
        u.is_active = False
        u.save()
        call_command("device_reset_password", "admin", stdout=StringIO())
        u.refresh_from_db()
        self.assertTrue(u.is_active and u.check_password("pgpro"))
        self.assertTrue(u.device_profile.must_change_password)

    def test_unknown_user_errors(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("device_reset_password", "nobody", stdout=StringIO())


class BasemapTests(TestCase):
    def test_vector_scripts_only_when_basemap_exists(self):
        import tempfile
        from pathlib import Path

        from django.template.loader import render_to_string
        from django.test import RequestFactory, override_settings

        from device.context import device
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(OSM_ROOT=Path(tmp)):
                self.assertEqual(device(RequestFactory().get("/"))["DEVICE_BASEMAP_URL"], "")
                (Path(tmp) / "basemap").mkdir()
                (Path(tmp) / "basemap" / "iran.pmtiles").write_bytes(b"x")
                url = device(RequestFactory().get("/"))["DEVICE_BASEMAP_URL"]
        self.assertEqual(url, "/basemap/style.json")
        html = render_to_string("partials/leaflet_vector.html", {"DEVICE_BASEMAP_URL": url})
        self.assertIn("leaflet-maplibre-gl.js", html)
        self.assertIn('data-style="/basemap/style.json"', html)
        self.assertEqual(render_to_string("partials/leaflet_vector.html", {"DEVICE_BASEMAP_URL": ""}).strip(), "")


class VectorAssetsTests(TestCase):
    def test_vector_assets_for_lazy_leaflet(self):
        import tempfile
        from pathlib import Path

        from django.test import override_settings

        from device.context import vector_assets
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(OSM_ROOT=Path(tmp)):
                self.assertIsNone(vector_assets())
                (Path(tmp) / "basemap").mkdir()
                (Path(tmp) / "basemap" / "iran.pmtiles").write_bytes(b"x")
                v = vector_assets()
        self.assertEqual(v["style"], "/basemap/style.json")
        for key in ("css", "maplibre_js", "plugin_js", "helper_js", "rtl_js"):
            self.assertTrue(v[key].startswith("/static/"), key)

    def test_cloud_view_helper_is_none_without_device_mode(self):
        from django.test import override_settings

        from databases.views import _device_vector_assets
        with override_settings(DEVICE_MODE=False):
            self.assertIsNone(_device_vector_assets())


class UpdateUiTests(Base):
    def setUp(self):
        super().setUp()
        self.login_ready()

    def test_status_idle_and_parsed(self):
        import os
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["PGPRO_DATA"] = tmp
            try:
                self.assertEqual(self.client.get("/device/update/status/").json()["state"], "idle")
                (Path(tmp) / "update.state").write_text("running|دانلود نسخه‌ی 0.2\n", encoding="utf-8")
                (Path(tmp) / "update.log").write_text("\n".join(f"خط {i}" for i in range(30)), encoding="utf-8")
                j = self.client.get("/device/update/status/").json()
                self.assertEqual((j["state"], j["message"]), ("running", "دانلود نسخه‌ی 0.2"))
                self.assertEqual(len(j["log"]), 12)
                (Path(tmp) / "update.state").write_text("bogus|x", encoding="utf-8")
                self.assertEqual(self.client.get("/device/update/status/").json()["state"], "idle")
            finally:
                os.environ.pop("PGPRO_DATA", None)

    def test_start_needs_admin_and_post(self):
        from unittest import mock
        self.assertEqual(self.client.get("/device/update/").status_code, 405)
        with mock.patch("device.views.update.start", return_value=(True, "به‌روزرسانی شروع شد.")) as m:
            r = self.client.post("/device/update/", {"mode": "update"})
            self.assertEqual(r.status_code, 200)
            m.assert_called_once_with(check_only=False)
        with mock.patch("device.views.update.start", return_value=(False, "یک به‌روزرسانی در جریان است.")):
            self.assertEqual(self.client.post("/device/update/", {}).status_code, 400)
        self.client.logout()
        services.create_user("sara", "Rah-Neshan-91", phone="09121234567", must_change=False)
        self.login("sara", "Rah-Neshan-91")
        self.assertEqual(self.client.post("/device/update/", {}).status_code, 302)
        self.assertEqual(self.client.get("/device/update/status/").status_code, 302)

    def test_start_runs_sudo_with_exact_args(self):
        from unittest import mock

        from device import update
        with mock.patch.object(update, "UPDATER", "/bin/true"), mock.patch("device.update.subprocess.run") as run:
            run.return_value.returncode = 0
            ok, _ = update.start()
        self.assertTrue(ok)
        self.assertEqual(run.call_args[0][0], ["sudo", "-n", "/bin/true", "--latest", "--detach"])

    def test_start_without_updater_installed(self):
        from unittest import mock

        from device import update
        with mock.patch.object(update, "UPDATER", "/nonexistent/pgpro-update"):
            ok, msg = update.start()
        self.assertFalse(ok)
        self.assertIn("نصب نیست", msg)

    def test_system_page_shows_update_card(self):
        self.assertContains(self.client.get("/device/system/"), "نسخه و به‌روزرسانی")
