from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from databases import services
from databases.crypto import decrypt, encrypt, scram_sha256_verifier
from databases.models import DatabaseServer, Extension, Plan, UserDatabase
from databases.provisioner import ProvisionError


class FakeProvisioner:
    """جایگزین سرور واقعی برای تست منطق کسب‌وکار."""

    def __init__(self):
        self.calls = []
        self.sizes = {}
        self.fail_create = False

    def create_tenant(self, name, role, password, extensions, limits):
        self.calls.append(("create", name, role, tuple(extensions), limits.connection_limit))
        if self.fail_create:
            raise ProvisionError("boom")
        return list(extensions)

    def database_sizes(self, names):
        return {n: self.sizes.get(n, 1000) for n in names}

    def __getattr__(self, item):
        def rec(*args, **kwargs):
            self.calls.append((item, *args))
        return rec


class BaseCase(TestCase):
    def setUp(self):
        self.fake = FakeProvisioner()
        patcher = mock.patch.object(services, "provisioner_for", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = DatabaseServer(name="s1", host="10.0.0.5", public_host="db.postgis.ir", is_default=True)
        self.server.set_admin_password("secret")
        self.server.save()
        self.plan = Plan.objects.get(slug="free")  # از مایگریشن seed
        self.user = User.objects.create_user("09120000001")


class CryptoTests(TestCase):
    def test_encrypt_roundtrip(self):
        token = encrypt("hello")
        self.assertNotIn("hello", token)
        self.assertEqual(decrypt(token), "hello")

    def test_scram_format(self):
        v = scram_sha256_verifier("abc")
        self.assertTrue(v.startswith("SCRAM-SHA-256$4096:"))
        self.assertEqual(len(v.split("$")), 3)
        self.assertNotEqual(v, scram_sha256_verifier("abc"))  # salt تصادفی


class SeedTests(TestCase):
    def test_defaults_seeded(self):
        self.assertTrue(Extension.objects.filter(name="postgis", is_default=True).exists())
        self.assertTrue(Plan.objects.filter(slug="free", is_default=True).exists())


class CreateDatabaseTests(BaseCase):
    def test_create_success(self):
        db = services.create_database(self.user, "tehran", "Abcdefgh123", ["postgis", "not_allowed"])
        self.assertEqual(db.status, UserDatabase.Status.ACTIVE)
        self.assertEqual(db.db_name, "gp_tehran")
        self.assertEqual(db.role_name, "gp_tehran_user")
        self.assertEqual(self.fake.calls[0], ("create", "gp_tehran", "gp_tehran_user", ("postgis",), 5))
        self.assertEqual([e.name for e in db.extensions.all()], ["postgis"])
        self.assertIsNotNone(db.expires_at)
        self.assertEqual(db.size_bytes, 1000)

    def test_custom_username(self):
        db = services.create_database(self.user, "city", "Abcdefgh123", [], username="ali_gis")
        self.assertEqual((db.db_name, db.role_name), ("gp_city", "gp_ali_gis"))

    def test_username_must_differ_and_be_unique(self):
        with self.assertRaises(services.ServiceError):
            services.create_database(self.user, "same", "Abcdefgh123", [], username="same")

    def test_limit_per_user(self):
        services.create_database(self.user, "one", "Abcdefgh123", [])
        with self.assertRaises(services.ServiceError):
            services.create_database(self.user, "two", "Abcdefgh123", [])

    def test_failure_marks_error(self):
        self.fake.fail_create = True
        with self.assertRaises(services.ServiceError):
            services.create_database(self.user, "bad", "Abcdefgh123", [])
        self.assertEqual(UserDatabase.objects.get().status, UserDatabase.Status.ERROR)

    def test_no_server(self):
        self.server.is_active = False
        self.server.save()
        with self.assertRaises(services.ServiceError):
            services.create_database(self.user, "x_db", "Abcdefgh123", [])

    def test_delete_frees_name(self):
        db = services.create_database(self.user, "reuse", "Abcdefgh123", [])
        services.delete_database(db)
        db.refresh_from_db()
        self.assertEqual(db.status, UserDatabase.Status.DELETED)
        self.assertIn(("drop_tenant", "gp_reuse", "gp_reuse_user"), self.fake.calls)
        # نام دوباره قابل استفاده است
        services.create_database(self.user, "reuse", "Abcdefgh123", [])


class QuotaExpiryTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, "q_db", "Abcdefgh123", [])

    def test_over_quota_goes_readonly_and_back(self):
        self.fake.sizes["gp_q_db"] = self.plan.quota_bytes + 1
        services.check_quotas()
        self.db.refresh_from_db()
        self.assertEqual(self.db.status, UserDatabase.Status.READONLY)
        self.assertIn(("set_readonly", "gp_q_db", True), self.fake.calls)

        self.fake.sizes["gp_q_db"] = 10
        services.check_quotas()
        self.db.refresh_from_db()
        self.assertEqual(self.db.status, UserDatabase.Status.ACTIVE)

    def test_expiry_lifecycle(self):
        self.db.expires_at = timezone.now() - timedelta(minutes=1)
        self.db.save()
        services.process_expiry()
        self.db.refresh_from_db()
        self.assertEqual(self.db.status, UserDatabase.Status.EXPIRED)
        self.assertIn(("set_login", "gp_q_db_user", False), self.fake.calls)

        services.renew(self.db)
        self.db.refresh_from_db()
        self.assertEqual(self.db.status, UserDatabase.Status.ACTIVE)
        self.assertGreater(self.db.days_left, 80)

    def test_deleted_after_grace(self):
        self.db.status = UserDatabase.Status.EXPIRED
        self.db.expires_at = timezone.now() - timedelta(days=services.conf().expired_grace_days + 1)
        self.db.save()
        services.process_expiry()
        self.db.refresh_from_db()
        self.assertEqual(self.db.status, UserDatabase.Status.DELETED)


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                             "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class ViewTests(BaseCase):
    def test_public_pages(self):
        for url in ["/", "/docs/", "/docs/qgis/", "/docs/srid/", "/terms/", "/accounts/login/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(self.client.get("/docs/nope/").status_code, 404)
        self.assertEqual(self.client.get("/healthz").json(), {"status": "ok"})

    def test_dashboard_requires_login(self):
        r = self.client.get(reverse("databases:dashboard"))
        self.assertEqual(r.status_code, 302)

    def test_signup_then_create_flow(self):
        self.client.post(reverse("accounts:login"), {"phone": "۰۹۱۲۳۴۵۶۷۸۹"})
        from accounts.models import OTPCode
        otp = OTPCode.objects.get(phone="09123456789")
        with mock.patch("accounts.models._hash_code", return_value=otp.code_hash):
            r = self.client.post(reverse("accounts:verify"), {"code": "11111", "full_name": "سارا",
                                                              "accept_terms": "on"})
        self.assertRedirects(r, reverse("databases:create"), fetch_redirect_response=False)
        pg = Extension.objects.get(name="postgis")
        r = self.client.post(reverse("databases:create"), {
            "label": "my_proj", "password": "Abcdefgh1234", "extensions": [pg.pk]})
        db = UserDatabase.objects.get(db_name="gp_my_proj")
        self.assertRedirects(r, reverse("databases:detail", args=[db.pk]), fetch_redirect_response=False)
        page = self.client.get(reverse("databases:detail", args=[db.pk])).content.decode()
        self.assertIn("Abcdefgh1234", page)  # رمز یک‌بار نمایش داده می‌شود
        page = self.client.get(reverse("databases:detail", args=[db.pk])).content.decode()
        self.assertNotIn("Abcdefgh1234", page)  # و دیگر نه

    def test_create_validation(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("databases:create"), {"label": "Bad-Name", "password": "short"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(UserDatabase.objects.exists())
        r = self.client.post(reverse("databases:create"), {"label": "postgres", "password": "Abcdefgh1234"})
        self.assertFalse(UserDatabase.objects.exists())

    def test_other_users_db_hidden(self):
        db = services.create_database(self.user, "mine", "Abcdefgh123", [])
        other = User.objects.create_user("09120000002")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("databases:detail", args=[db.pk])).status_code, 404)
        self.client.post(reverse("databases:delete", args=[db.pk]), {"confirm": "mine"})
        db.refresh_from_db()
        self.assertEqual(db.status, UserDatabase.Status.ACTIVE)

    def test_delete_requires_confirmation(self):
        db = services.create_database(self.user, "del_me", "Abcdefgh123", [])
        self.client.force_login(self.user)
        self.client.post(reverse("databases:delete", args=[db.pk]), {"confirm": "wrong"})
        db.refresh_from_db()
        self.assertEqual(db.status, UserDatabase.Status.ACTIVE)
        self.client.post(reverse("databases:delete", args=[db.pk]), {"confirm": "del_me"})
        db.refresh_from_db()
        self.assertEqual(db.status, UserDatabase.Status.DELETED)

    def test_admin_server_pages(self):
        admin = User.objects.create_admin("boss", "Adm1nPassword!")
        self.client.force_login(admin)
        self.assertEqual(self.client.get("/manage/databases/databaseserver/").status_code, 200)
        self.assertEqual(self.client.get(f"/manage/databases/databaseserver/{self.server.pk}/change/").status_code, 200)
        page = self.client.get(f"/manage/databases/databaseserver/{self.server.pk}/change/").content.decode()
        self.assertNotIn("secret", page)  # رمز ادمین هرگز نمایش داده نمی‌شود
