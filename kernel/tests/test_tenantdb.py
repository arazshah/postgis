"""دروازه‌ی داده‌ی مشتری: اتصال فقط از اتصال‌دهنده‌ی ثبت‌شده، تلاش دوباره با نقش تازه، و نوشتن با نقش مالک."""
from types import SimpleNamespace
from unittest import mock

import psycopg
from django.test import SimpleTestCase

from kernel import tenantdb


class FakeConnector(tenantdb.Connector):
    def __init__(self):
        self.calls = []

    def params(self, ws, force=False):
        self.calls.append(force)
        return {"dbname": ws.name, "user": "u_web", "password": "new" if force else "old"}

    def owner_role(self, ws):
        return 'own"er'


class TenantDbTests(SimpleTestCase):
    def setUp(self):
        self.link = FakeConnector()
        self.ws = SimpleNamespace(name="d1")
        p = mock.patch.object(tenantdb, "_connector", self.link)
        p.start()
        self.addCleanup(p.stop)
        c = mock.patch.object(tenantdb, "_catalog_path", "")
        c.start()
        self.addCleanup(c.stop)

    def test_read_only_by_default_and_closes(self):
        conn = mock.MagicMock()
        with mock.patch("psycopg.connect", return_value=conn) as connect:
            with tenantdb.connect(self.ws) as got:
                self.assertIs(got, conn)
                self.assertTrue(conn.read_only)
                conn.execute.assert_not_called()
        connect.assert_called_once_with(dbname="d1", user="u_web", password="old")
        conn.close.assert_called_once()

    def test_owner_write_sets_role_with_quoted_identifier(self):
        conn = mock.MagicMock()
        with mock.patch("psycopg.connect", return_value=conn):
            with tenantdb.connect(self.ws, write=True, as_owner=True):
                pass
        self.assertFalse(conn.read_only)
        stmt = conn.execute.call_args.args[0].as_string(None)
        self.assertEqual(stmt, 'SET ROLE "own""er"')

    def test_retries_once_with_a_fresh_role_then_reports_persian_error(self):
        conn = mock.MagicMock()
        boom = psycopg.OperationalError("password authentication failed for user")
        with mock.patch("psycopg.connect", side_effect=[boom, conn]):
            with tenantdb.connect(self.ws):
                pass
        self.assertEqual(self.link.calls, [False, True])
        with mock.patch("psycopg.connect", side_effect=psycopg.OperationalError("timeout")):
            with self.assertRaisesMessage(tenantdb.TenantError, "اتصال به پایگاه داده ممکن نشد"):
                with tenantdb.connect(self.ws):
                    pass

    def test_no_connector_is_a_clear_error(self):
        with mock.patch.object(tenantdb, "_connector", None):
            with self.assertRaises(tenantdb.TenantError):
                tenantdb.connector()

    def test_installed_project_registers_postgis_connector_and_full_catalog(self):
        from databases.explorer import Explorer, ExplorerError
        from databases.gateway import PostgisConnector

        self.assertIs(ExplorerError, tenantdb.TenantError)
        self.assertTrue(issubclass(Explorer, tenantdb.Catalog))
        mock.patch.stopall()
        self.assertIsInstance(tenantdb.connector(), PostgisConnector)
        self.assertIsInstance(tenantdb.catalog(SimpleNamespace(server=None)), Explorer)
