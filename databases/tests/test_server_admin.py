from unittest import mock

from django.test import TestCase

from accounts.models import User
from databases.models import DatabaseServer, parse_postgres_url
from databases.provisioner import Provisioner, ProvisionError, ServerInfo

COOLIFY_URL = ("postgres://postgres:S3cr%40tPass@kw8sgoc4wks0cg8o0skog4kk-093421987654:5432/postgres")


class ParseTests(TestCase):
    def test_parse_coolify_url(self):
        p = parse_postgres_url(COOLIFY_URL)
        self.assertEqual(p["host"], "kw8sgoc4wks0cg8o0skog4kk-093421987654")
        self.assertEqual(p["port"], 5432)
        self.assertEqual(p["user"], "postgres")
        self.assertEqual(p["password"], "S3cr@tPass")
        self.assertEqual(p["dbname"], "postgres")

    def test_plain_host_not_parsed(self):
        self.assertIsNone(parse_postgres_url("db.postgis.ir"))

    def test_bad_host_never_raises_raw_error(self):
        p = Provisioner({"host": "x" * 200, "port": 5432, "user": "u", "password": "p", "dbname": "postgres",
                         "connect_timeout": 2})
        with self.assertRaises(ProvisionError):
            p.harden()
        self.assertFalse(p.check().ok)


class ServerAdminTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_admin("admin", "Str0ng-Admin-Pass"))
        fake = mock.Mock()
        fake.check.return_value = ServerInfo(ok=True, message="اتصال برقرار است.", server_version="17",
                                             postgis_version="3.5")
        fake.harden.return_value = ["ok"]
        p = mock.patch("databases.services.provisioner_for", return_value=fake)
        p.start()
        self.addCleanup(p.stop)

    def post(self, **over):
        data = {"name": "db1", "host": COOLIFY_URL, "port": "5432", "admin_user": "x", "admin_password": "",
                "admin_database": "postgres", "sslmode": "prefer", "public_host": "db.postgis.ir",
                "public_port": "5434", "public_sslmode": "require", "is_active": "on", "is_default": "on",
                "max_databases": "150", "disk_capacity_gb": "0", "notes": ""}
        data.update(over)
        return self.client.post("/manage/databases/databaseserver/add/", data)

    def test_paste_full_url_fills_fields(self):
        r = self.post()
        self.assertEqual(r.status_code, 302, r.content.decode()[:3000])
        s = DatabaseServer.objects.get()
        self.assertEqual(s.host, "kw8sgoc4wks0cg8o0skog4kk-093421987654")
        self.assertEqual(s.admin_user, "postgres")
        self.assertEqual(s.get_admin_password(), "S3cr@tPass")
        self.assertNotIn("S3cr", s.host + s.admin_password_encrypted)
        self.assertEqual(s.public_port, 5434)

    def test_invalid_host_shows_form_error_not_500(self):
        r = self.post(host="this is not a host", admin_password="pw")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "فقط نام میزبان یا IP")
        self.assertFalse(DatabaseServer.objects.exists())

    def test_public_host_scheme_stripped(self):
        r = self.post(public_host="https://db.postgis.ir/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(DatabaseServer.objects.get().public_host, "db.postgis.ir")
