"""
تست روی یک سرور واقعی PostgreSQL + PostGIS.
فقط وقتی اجرا می‌شود که TEST_PG_HOST تنظیم شده باشد (در CI با سرویس postgis/postgis).
"""
import os
import unittest
import uuid

import psycopg
from django.test import SimpleTestCase

from databases.provisioner import Provisioner, ProvisionError, TenantLimits

PG = dict(
    host=os.environ.get("TEST_PG_HOST", ""),
    port=int(os.environ.get("TEST_PG_PORT", "5432")),
    user=os.environ.get("TEST_PG_USER", "postgres"),
    password=os.environ.get("TEST_PG_PASSWORD", "postgres"),
    dbname="postgres",
    sslmode="disable",
    connect_timeout=5,
)


@unittest.skipUnless(PG["host"], "TEST_PG_HOST not set")
class ProvisionerIntegrationTests(SimpleTestCase):
    def setUp(self):
        self.p = Provisioner(PG)
        self.name = f"gp_it_{uuid.uuid4().hex[:8]}"
        self.pw = "Integr4tionPass"
        self.addCleanup(self.p.drop_tenant, self.name)

    def tenant_conn(self, dbname=None, password=None):
        return psycopg.connect(host=PG["host"], port=PG["port"], user=self.name, password=password or self.pw,
                               dbname=dbname or self.name, sslmode="disable", autocommit=True, connect_timeout=5)

    def test_check(self):
        info = self.p.check()
        self.assertTrue(info.ok, info.message)
        self.assertTrue(info.postgis_version)

    def test_full_lifecycle(self):
        installed = self.p.create_tenant(self.name, self.pw, ["postgis", "postgis_topology"],
                                         TenantLimits(connection_limit=3, statement_timeout_s=30))
        self.assertEqual(installed, ["postgis", "postgis_topology"])
        with self.tenant_conn() as c:
            self.assertEqual(c.execute("SHOW statement_timeout").fetchone()[0], "30s")
            c.execute("CREATE TABLE pts (id serial, g geometry(Point,4326))")
            c.execute("INSERT INTO pts(g) VALUES (ST_SetSRID(ST_MakePoint(51.4,35.7),4326))")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                c.execute("CREATE DATABASE nope")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                c.execute("SET temp_file_limit = '100GB'")

        self.assertGreater(self.p.database_sizes([self.name])[self.name], 0)

        self.p.set_readonly(self.name, True)
        with self.tenant_conn() as c, self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
            c.execute("INSERT INTO pts(g) VALUES (NULL)")
        self.p.set_readonly(self.name, False)

        self.p.set_password(self.name, "Brand2NewPass")
        with self.tenant_conn(password="Brand2NewPass") as c:
            c.execute("INSERT INTO pts(g) VALUES (NULL)")

        self.p.install_extension(self.name, "fuzzystrmatch")
        self.assertIn("fuzzystrmatch", self.p.installed_extensions(self.name))

        self.p.set_login(self.name, False)
        with self.assertRaises(psycopg.OperationalError):
            self.tenant_conn(password="Brand2NewPass")

        self.p.drop_tenant(self.name)
        self.assertEqual(self.p.database_sizes([self.name]), {})

    def test_harden(self):
        done = self.p.harden()
        self.assertTrue(any("postgres" in d for d in done))
        self.assertTrue(self.p.check().hardened)
        self.p.create_tenant(self.name, self.pw, [], TenantLimits())
        with self.assertRaises(psycopg.OperationalError):
            self.tenant_conn(dbname="postgres")  # کاربر مشتری به دیتابیس سیستمی راه ندارد
        with self.tenant_conn() as c:
            self.assertEqual(c.execute("SELECT 1").fetchone()[0], 1)

    def test_rollback_on_bad_extension(self):
        with self.assertRaises(ProvisionError):
            self.p.create_tenant(self.name, self.pw, ["postgis", "does_not_exist_ext"], TenantLimits())
        self.assertEqual(self.p.database_sizes([self.name]), {})

    def test_rejects_bad_identifiers(self):
        for bad in ["Upper", "a; drop", "x", "1abc", "pg x"]:
            with self.assertRaises(ProvisionError):
                self.p.create_tenant(bad, self.pw, [], TenantLimits())
        with self.assertRaises(ProvisionError):
            self.p.create_tenant(self.name, self.pw, ["postgis; drop"], TenantLimits())
