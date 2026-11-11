"""قراردادهای میزبانی، چرخه‌ی عمر فضای کار و ورود/خروج داده (kernel.workspace و kernel.dataio)."""
from types import SimpleNamespace
from unittest import mock

from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, SimpleTestCase, TestCase

from kernel import dataio, workspace


class InstalledHostingTests(TestCase):
    def test_errors_form_one_family(self):
        from databases.gdal import GdalError
        from databases.provisioner import ProvisionError
        from databases.services import ServiceError

        self.assertTrue(issubclass(ProvisionError, workspace.HostingError))
        self.assertTrue(issubclass(workspace.HostingError, workspace.WorkspaceError))
        self.assertTrue(issubclass(ServiceError, workspace.WorkspaceError))
        self.assertTrue(issubclass(GdalError, dataio.DataIOError))

    def test_role_names_match_the_provisioner_rules(self):
        from databases.provisioner import Provisioner

        ws = SimpleNamespace(role_name="gp_" + "x" * 70)
        self.assertEqual(workspace.role_name(ws, "browser"), Provisioner.browser_role_name(ws.role_name))
        self.assertEqual(workspace.role_name(ws, "ows"), Provisioner.ows_role_name(ws.role_name))
        self.assertTrue(workspace.role_name(ws, "browser").endswith("_web"))
        with self.assertRaises(ValueError):
            workspace.role_name(ws, "nope")

    def test_host_goes_through_the_replaceable_provisioner_hook(self):
        marker = object()
        with mock.patch("databases.services.provisioner_for", return_value=marker) as hook:
            self.assertIs(workspace.host(SimpleNamespace(server="srv")), marker)
        hook.assert_called_once_with("srv")

    def test_limits_plan_defaults_and_event_log(self):
        from databases.models import ActivityLog

        plan = SimpleNamespace(max_connections=7, statement_timeout_s=11, temp_file_limit_mb=13)
        lim = workspace.limits(plan)
        self.assertEqual((lim.connection_limit, lim.statement_timeout_s, lim.temp_file_limit_mb), (7, 11, 13))
        self.assertEqual(workspace.plan_default("quota_mb"), 1024)
        self.assertEqual(workspace.plan_default("no_such_field", 5), 5)
        workspace.log_event("kernel_test", "پیام", success=False)
        row = ActivityLog.objects.get(action="kernel_test")
        self.assertEqual((row.message, row.success), ("پیام", False))

    def test_notify_user_is_best_effort(self):
        user = SimpleNamespace(phone="09120000000", email="")
        with mock.patch("accounts.sms.send_text", side_effect=RuntimeError("down")), self.assertLogs("databases.services", "ERROR"):
            workspace.notify_user(user, "موضوع", "متن")  # خطای پیامک پیام را نمی‌شکند

    def test_open_catalog_reports_inactive_workspace_in_persian(self):
        req = RequestFactory().get("/")
        req.session = {}
        req._messages = FallbackStorage(req)
        ws = SimpleNamespace(is_live=False)
        with mock.patch.object(workspace, "get", return_value=ws):
            got, cat = workspace.open_catalog(req, 1, "editor")
        self.assertIs(got, ws)
        self.assertIsNone(cat)
        self.assertIn("فعال", " ".join(str(m) for m in req._messages))


class FakeData(dataio.Provider):
    def __init__(self):
        self.calls = []

    def import_layer(self, ws, path, layer, encoding):
        self.calls.append(("import", ws, str(path), layer["table"], encoding))

    def run_gdal(self, tool, args, *, env=None, timeout=None):
        self.calls.append(("run", tool, tuple(args), env, timeout))
        return "ok"

    def pg_target(self, ws):
        return SimpleNamespace(conn="PG:x", env={})


class DataIOTests(SimpleTestCase):
    def test_functions_delegate(self):
        fake = FakeData()
        with mock.patch.object(dataio, "_provider", fake):
            dataio.import_layer("ws", "/a.geojson", {"table": "t"})
            self.assertEqual(dataio.run_gdal("ogr2ogr", ["-f", "X"], timeout=5), "ok")
            self.assertEqual(dataio.pg_target("ws").conn, "PG:x")
        self.assertEqual(fake.calls[0], ("import", "ws", "/a.geojson", "t", None))
        self.assertEqual(fake.calls[1], ("run", "ogr2ogr", ("-f", "X"), None, 5))

    def test_no_provider_is_a_clear_error(self):
        with mock.patch.object(dataio, "_provider", None):
            with self.assertRaises(dataio.DataIOError):
                dataio.pg_target("ws")

    def test_installed_provider_runs_gdal_tools_through_the_binary_lookup(self):
        from databases.gateway import GdalProvider

        self.assertIsInstance(dataio.provider(), GdalProvider)
        with mock.patch("databases.gdal._bin", return_value="/usr/bin/ogr2ogr") as binary, \
                mock.patch("databases.gdal._run", return_value="out") as run:
            self.assertEqual(dataio.run_gdal("ogr2ogr", ["--version"], env={"A": "1"}), "out")
        binary.assert_called_once_with("ogr2ogr")
        self.assertEqual(run.call_args.args[0], ["/usr/bin/ogr2ogr", "--version"])
