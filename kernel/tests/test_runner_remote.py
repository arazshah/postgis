"""سرویس plugin-runner (حالت remote) و پل SQL میزبان."""
import json
import os
import threading
import urllib.error
import urllib.request
from unittest import mock

from django.core import signing
from django.test import SimpleTestCase, TestCase, override_settings

from kernel import handlers
from kernel.plugins import registry
from kernel.runner import client, remote, server

CODE = "def handle(ctx, p):\n    r = ctx.sql('select 1')\n    return {'columns': ['v'], 'rows': [[r['rows'][0][0] + p['n']]]}"
TOKEN = "t0ken-for-tests"


class RunnerServerTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._env = mock.patch.dict(os.environ, {"RUNNER_TOKEN": TOKEN})
        cls._env.start()
        cls.srv = server.serve("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls._env.stop()
        super().tearDownClass()

    def post(self, body, token=TOKEN, path="/run"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def body(self, **over):
        return {"files": {"code/h.py": CODE}, "handler": "h", "params": {"n": 41}, "timeout": 5,
                "callback": {"url": "http://host.invalid/internal/runner/sql/", "token": "job"}, **over}

    def test_requires_token(self):
        self.assertEqual(self.post(self.body(), token="wrong")[0], 403)
        self.assertEqual(self.post(self.body(), token="")[0], 403)
        self.assertEqual(self.post(self.body(), path="/other")[0], 403)

    def test_runs_code_with_sql_callback(self):
        with mock.patch("kernel.runner.server.make_sql", return_value=lambda q, p: {"columns": ["v"], "rows": [[1]]}):
            code, out = self.post(self.body())
        self.assertEqual((code, out), (200, {"ok": True, "value": {"columns": ["v"], "rows": [[42]]}}))

    def test_bad_requests_and_code_errors(self):
        self.assertEqual(self.post({"files": {}})[0], 400)
        self.assertEqual(self.post(self.body(callback={"url": "file:///etc/passwd", "token": "x"}))[0], 400)
        with mock.patch("kernel.runner.server.make_sql", return_value=lambda q, p: {}):
            code, out = self.post(self.body(files={"code/h.py": "def handle(c, p):\n    return 1/0"}))
        self.assertEqual(code, 200)
        self.assertFalse(out["ok"])
        self.assertIn("ZeroDivisionError", out["error"])

    def test_health(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/healthz", timeout=5) as r:
            self.assertEqual(json.loads(r.read()), {"ok": True})


class RemoteClientTests(TestCase):
    def setUp(self):
        registry.register("compute", "محاسبه", kind="custom")
        self.addCleanup(registry.remove_plugin, "compute")
        handlers.register("compute", "h", CODE)

    @override_settings(PLUGIN_RUNNER_MODE="remote", PLUGIN_RUNNER_URL="", PLUGIN_RUNNER_TOKEN="", PLUGIN_RUNNER_CALLBACK="")
    def test_unconfigured_remote_is_refused(self):
        with self.assertRaisesMessage(client.RunnerError, "تنظیم نشده"):
            client.execute("compute", "h", {}, None, 5)

    @override_settings(PLUGIN_RUNNER_MODE="remote", PLUGIN_RUNNER_URL="http://x", PLUGIN_RUNNER_TOKEN="t", PLUGIN_RUNNER_CALLBACK="http://w")
    def test_needs_workspace_and_hides_network_errors(self):
        with self.assertRaises(client.RunnerError):
            client.execute("compute", "h", {}, None, 0)
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("secret-host:1234 refused")), \
                self.assertRaises(client.RunnerError) as cm:
            client.execute("compute", "h", {}, None, 5)
        self.assertNotIn("secret-host", str(cm.exception))

    def test_job_token_is_short_lived_and_bound_to_one_workspace(self):
        tok = remote.job_token(7)
        self.assertEqual(remote.read_job_token(tok), 7)
        with self.assertRaises(signing.BadSignature):
            remote.read_job_token(tok + "x")
        with mock.patch("django.core.signing.time.time", return_value=__import__("time").time() + 3600), \
                self.assertRaises(signing.SignatureExpired):
            remote.read_job_token(tok)


class RunnerSqlViewTests(TestCase):
    def post(self, token, body=None):
        return self.client.post("/internal/runner/sql/", data=json.dumps(body or {"query": "select 1"}), content_type="application/json",
                                HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_rejects_missing_or_forged_token(self):
        self.assertEqual(self.post("").status_code, 403)
        self.assertEqual(self.post("garbage").status_code, 403)
        self.assertEqual(self.post(signing.dumps({"ws": 1}, salt="other")).status_code, 403)

    def test_valid_token_runs_select_via_read_select(self):
        ws = mock.Mock(pk=3, is_live=True)
        with mock.patch("kernel.workspace.peek", return_value=ws) as peek, \
                mock.patch("kernel.pagekit.read_select", return_value={"columns": ["a"], "rows": [[1]]}) as rs:
            r = self.post(remote.job_token(3), {"query": "select 1", "params": [1]})
        self.assertEqual(r.json(), {"columns": ["a"], "rows": [[1]]})
        peek.assert_called_once_with(3)
        rs.assert_called_once_with(ws, "select 1", [1])

    def test_inactive_workspace_and_write_attempts_are_errors_not_execution(self):
        with mock.patch("kernel.workspace.peek", return_value=None):
            self.assertIn("error", self.post(remote.job_token(3)).json())
        ws = mock.Mock(pk=3, is_live=True)
        with mock.patch("kernel.workspace.peek", return_value=ws), mock.patch("kernel.tenantdb.connect") as conn:
            r = self.post(remote.job_token(3), {"query": "delete from t"})
        self.assertIn("SELECT", r.json()["error"])
        conn.assert_not_called()

    def test_get_not_allowed_and_not_csrf_blocked(self):
        self.assertEqual(self.client.get("/internal/runner/sql/").status_code, 405)
