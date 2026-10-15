"""PgBouncer (auth_query با SCRAM) و داشبورد مصرف روی سرور واقعی."""
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

import psycopg
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from databases import services as db_services
from databases import team, usage
from databases.models import DatabaseServer, Plan, SizeSample
from databases.provisioner import Provisioner

PG_HOST = os.environ.get("TEST_PG_HOST", "")
PGBOUNCER = shutil.which("pgbouncer") or ("/usr/sbin/pgbouncer" if Path("/usr/sbin/pgbouncer").exists() else None)
DOCKER_DIR = Path(settings.BASE_DIR) / "docker" / "pgbouncer"


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
@override_settings(ALLOWED_HOSTS=["testserver"])
class PoolerUsageTests(TestCase):
    def setUp(self):
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        self.server = server
        Provisioner.for_server(server).harden()
        self.user = User.objects.create_user("09120000061")
        self.db = db_services.create_database(self.user, f"pu_{uuid.uuid4().hex[:8]}", "Pool-Pass-123", ["postgis"])
        self.addCleanup(self._drop)
        self.kw = dict(host=server.host, port=server.port, user=self.db.role_name, password="Pool-Pass-123",
                       dbname=self.db.db_name, autocommit=True)
        with psycopg.connect(**self.kw) as c:
            c.execute("CREATE TABLE big(id int, v text)")  # بدون کلید اصلی
            c.execute("INSERT INTO big SELECT g, md5(g::text) FROM generate_series(1, 20000) g")
            c.execute("ANALYZE big")
            for _ in range(60):
                c.execute("SELECT count(*) FROM big WHERE v = 'x'")

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    # ------------------------------------------------------------------ مصرف
    def test_usage_page(self):
        self.client.force_login(self.user)
        SizeSample.objects.create(database=self.db, day="2026-10-01", size_bytes=1000)
        url = reverse("databases:usage", args=[self.db.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        stats = r.context["stats"]
        self.assertEqual(stats["tables"][0]["name"], "big")
        kinds = {(s["kind"], s["table"]) for s in stats["suggestions"]}
        self.assertIn(("index", "public.big"), kinds)
        self.assertIn(("pk", "public.big"), kinds)
        self.assertContains(r, "<svg class=\"u-chart\"", count=2)
        # مشاهده‌گر تیم صفحه مصرف را نمی‌بیند
        self.db.plan = Plan.objects.create(name="p", slug="t-pu", is_free=False, team_members=2)
        self.db.save(update_fields=["plan"])
        team.invite(self.db, self.user, "09120000062", "viewer")
        self.client.force_login(User.objects.create_user("09120000062"))
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_running_query_cancel(self):
        done = {}

        def slow():
            try:
                with psycopg.connect(**self.kw) as c:
                    c.execute("SELECT pg_sleep(20)")
            except psycopg.errors.QueryCanceled:
                done["cancelled"] = True

        t = threading.Thread(target=slow)
        t.start()
        for _ in range(50):
            running = usage.collect(self.db)["running"]
            if running:
                break
            time.sleep(0.1)
        self.assertEqual(running[0]["user"], self.db.role_name)
        # pid دیتابیس دیگر (اتصال مدیر) قابل توقف نیست
        with psycopg.connect(**self.server.connection_kwargs(), autocommit=True) as admin:
            other = admin.execute("SELECT pg_backend_pid()").fetchone()[0]
            self.assertFalse(usage.cancel(self.db, other))
        self.client.force_login(self.user)
        self.client.post(reverse("databases:usage", args=[self.db.pk]), {"pid": running[0]["pid"]})
        t.join(10)
        self.assertTrue(done.get("cancelled"))

    # ------------------------------------------------------------------ PgBouncer
    @unittest.skipUnless(PGBOUNCER and shutil.which("envsubst") and shutil.which("openssl"),
                         "pgbouncer/envsubst/openssl نصب نیست")
    def test_pgbouncer_scram_passthrough(self):
        p = Provisioner.for_server(self.server)
        p.ensure_pooler_auth("Pooler-Test-Pass-1")
        p.ensure_pooler_auth("Pooler-Test-Pass-1")  # چندباره
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        conf = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, conf, True)
        tmpl = (DOCKER_DIR / "pgbouncer.ini.tmpl").read_text().replace("listen_port = 6432", f"listen_port = {port}")
        (conf / "tmpl").write_text(tmpl)
        env = {**os.environ, "DB_HOST": self.server.host, "DB_PORT": str(self.server.port),
               "AUTH_PASSWORD": "Pooler-Test-Pass-1", "AUTH_DBNAME": self.server.admin_database,
               "CONF_DIR": str(conf), "TEMPLATE": str(conf / "tmpl"), "PATH": f"/usr/sbin:{os.environ['PATH']}"}
        cmd = ["sh", str(DOCKER_DIR / "start.sh")]
        if os.geteuid() == 0:  # pgbouncer با root اجرا نمی‌شود
            shutil.chown(conf, "postgres")
            os.chmod(conf, 0o777)
            cmd = ["runuser", "-u", "postgres", "--", "env", *[f"{k}={v}" for k, v in env.items()
                                                              if k in ("DB_HOST", "DB_PORT", "AUTH_PASSWORD",
                                                                       "AUTH_DBNAME", "CONF_DIR", "TEMPLATE", "PATH")],
                   *cmd]
            os.chmod(conf.parent, os.stat(conf.parent).st_mode | 0o005)
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(proc.kill)
        pool = dict(self.kw, host="127.0.0.1", port=port)
        for _ in range(50):
            try:
                with psycopg.connect(**pool, connect_timeout=2) as c:
                    self.assertEqual(c.execute("SELECT count(*) FROM big").fetchone()[0], 20000)
                break
            except psycopg.OperationalError as exc:
                last = exc
                time.sleep(0.2)
        else:
            self.fail(f"pgbouncer وصل نشد: {last}")
        with psycopg.connect(**pool, sslmode="require") as c:  # TLS سمت کاربر
            self.assertEqual(c.execute("SELECT current_user").fetchone()[0], self.db.role_name)
        with self.assertRaises(psycopg.OperationalError):
            psycopg.connect(**dict(pool, password="wrong")).close()
        admin = self.server.connection_kwargs()
        with self.assertRaises(psycopg.OperationalError):  # superuser از راه pooler نه
            psycopg.connect(host="127.0.0.1", port=port, user=admin["user"], password=admin["password"],
                            dbname=admin["dbname"]).close()
