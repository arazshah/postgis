"""مسیرهای وب NTRIP روی PostGIS واقعی (فقط وقتی TEST_PG_HOST تنظیم شده باشد)."""
import json
import os
import unittest
import uuid
from unittest import mock

from django.core.cache import cache
from django.core.signals import request_finished
from django.db import close_old_connections, connection
from django.test import Client, TestCase, override_settings

from accounts.models import User
from core.models import SiteSettings
from databases import services as db_services
from databases.models import DatabaseServer, Member
from databases.provisioner import Provisioner
from survey import ntrip, services
from survey.models import NtripProfile, NtripSession
from survey.tests.test_ntrip import GGA, FakeCaster

PG_HOST = os.environ.get("TEST_PG_HOST", "")


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
@override_settings(ALLOWED_HOSTS=["testserver"], NTRIP_ALLOW_PRIVATE=True)
class NtripViewTests(TestCase):
    def setUp(self):
        cache.clear()
        # بستن پاسخ جریانی سیگنال request_finished می‌فرستد و اتصال تراکنش آزمون را می‌بندد
        request_finished.disconnect(close_old_connections)
        self.addCleanup(request_finished.connect, close_old_connections)
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.owner = User.objects.create_user("09120000061")
        self.viewer = User.objects.create_user("09120000062")
        self.db = db_services.create_database(self.owner, f"sn_{uuid.uuid4().hex[:8]}", "Ntrip-Pass-123", ["postgis"])
        self.addCleanup(self._drop)
        plan = self.db.plan
        plan.survey_projects, plan.gnss_external = 3, True
        plan.save()
        Member.objects.create(database=self.db, phone=self.viewer.phone, user=self.viewer, role="viewer")
        conf = SiteSettings.get()
        conf.survey_enabled = True
        conf.save()
        self.c = Client()
        self.c.force_login(self.owner)
        self.p = services.create_project(self.db, self.owner, "نمونه", 32639, "topo")
        self.base = f"/dashboard/{self.db.pk}/survey/{self.p.pk}/ntrip/"
        self.casters = []
        self.addCleanup(lambda: [c.close() for c in self.casters])

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def _post(self, url, body, client=None):
        return (client or self.c).post(url, json.dumps(body), content_type="application/json")

    def _save(self, port=2101, **kw):
        body = {"name": "شبکه", "host": "127.0.0.1", "port": port, "mountpoint": "MP1", "username": "u", "password": "secret-pw"}
        return self._post(self.base, body | kw)

    def test_password_is_encrypted_and_never_returned(self):
        r = self._save()
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("secret-pw", r.content.decode())
        self.assertTrue(r.json()["profile"]["has_password"])
        pr = NtripProfile.objects.get()
        self.assertNotIn("secret-pw", pr.password_enc)
        self.assertNotIn("secret-pw", self.c.get(self.base).content.decode())
        self._save(id=pr.pk, password="")  # خالی = بدون تغییر
        self.assertEqual(NtripProfile.objects.get().password_enc, pr.password_enc)

    def test_private_host_rejected_when_not_allowed(self):
        with override_settings(NTRIP_ALLOW_PRIVATE=False):
            self.assertEqual(self._save().status_code, 400)
            self.assertEqual(self._post(f"{self.base}sourcetable/", {"host": "127.0.0.1", "port": 80}).status_code, 502)
        self.assertEqual(NtripProfile.objects.count(), 0)

    def test_viewer_flag_and_plan_gates(self):
        v = Client()
        v.force_login(self.viewer)
        self.assertEqual(v.get(self.base).status_code, 404)
        plan = self.db.plan
        plan.gnss_external = False
        plan.save()
        self.assertEqual(self.c.get(self.base).status_code, 404)
        plan.gnss_external = True
        plan.save()
        conf = SiteSettings.get()
        conf.survey_enabled = False
        conf.save()
        self.assertEqual(self.c.get(self.base).status_code, 404)

    def test_full_relay_flow_with_heartbeat_and_stop(self):
        caster = FakeCaster()
        self.casters.append(caster)
        pid = self._save(port=caster.port).json()["profile"]["id"]
        s = self._post(f"{self.base}start/", {"id": pid, "gga": GGA}).json()
        self.assertTrue(s["stream"].endswith(f"/stream/{s['session']}/"))
        r = self.c.get(s["stream"])
        self.assertEqual(r.status_code, 200)
        it = iter(r.streaming_content)
        self.assertEqual(next(it), b"\xd3\x00\x13RTCM")
        self.assertEqual(self._post(f"{self.base}gga/{s['session']}/", {"gga": GGA}).status_code, 200)
        self.assertEqual(NtripSession.objects.get().gga_seq, 1)
        self.assertEqual(self._post(f"{self.base}gga/{s['session']}/", {"gga": "GET / evil"}).status_code, 200)
        self.assertEqual(NtripSession.objects.get().gga_seq, 1)  # GGA نامعتبر ذخیره نمی‌شود
        self._post(f"{self.base}stop/{s['session']}/", {})
        with mock.patch.object(connection, "close_if_unusable_or_obsolete"):  # بستن پاسخ جریانی اتصال آزمون را نبندد
            r.close()
        self.assertTrue(NtripSession.objects.get().closed)
        self.assertIn("Authorization: Basic", caster.requests[0])
        self.assertIn(GGA, caster.requests[0])

    def test_one_active_session_per_user_and_foreign_session_is_hidden(self):
        pid = self._save().json()["profile"]["id"]
        a = self._post(f"{self.base}start/", {"id": pid}).json()["session"]
        b = self._post(f"{self.base}start/", {"id": pid}).json()["session"]
        self.assertTrue(NtripSession.objects.get(pk=a).closed)
        self.assertFalse(NtripSession.objects.get(pk=b).closed)
        other = User.objects.create_user("09120000063")
        Member.objects.create(database=self.db, phone=other.phone, user=other, role="editor")
        o = Client()
        o.force_login(other)
        self.assertEqual(o.get(f"{self.base}stream/{b}/").status_code, 404)
        self.assertEqual(self._post(f"{self.base}gga/{b}/", {}, client=o).status_code, 404)

    def test_caster_errors_become_json_and_close_the_session(self):
        caster = FakeCaster(reply=b"HTTP/1.1 401 Unauthorized\r\n\r\n", payload=b"")
        self.casters.append(caster)
        pid = self._save(port=caster.port).json()["profile"]["id"]
        s = self._post(f"{self.base}start/", {"id": pid}).json()
        r = self.c.get(s["stream"])
        self.assertEqual(r.status_code, 502)
        self.assertIn("گذرواژه", r.json()["message"])
        self.assertTrue(NtripSession.objects.get().closed)

    def test_capacity_exhausted_returns_503(self):
        pid = self._save().json()["profile"]["id"]
        s = self._post(f"{self.base}start/", {"id": pid}).json()
        with mock.patch.object(ntrip._slots, "acquire", return_value=False):
            r = self.c.get(s["stream"])
        self.assertEqual(r.status_code, 503)

    def test_sourcetable_endpoint(self):
        caster = FakeCaster(table=True)
        self.casters.append(caster)
        r = self._post(f"{self.base}sourcetable/", {"host": "127.0.0.1", "port": caster.port, "username": "u", "password": "p"})
        self.assertEqual([m["mountpoint"] for m in r.json()["mountpoints"]], ["MP1", "MP2"])

    def test_stored_password_is_never_sent_to_a_different_host(self):
        caster = FakeCaster(table=True)
        self.casters.append(caster)
        pid = self._save(port=1).json()["profile"]["id"]  # گذرواژه ذخیره‌شده: secret-pw
        r = self._post(f"{self.base}sourcetable/", {"id": pid, "host": "127.0.0.1", "port": caster.port, "username": "u"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Basic dTo=", caster.requests[0])  # فقط «u:» با گذرواژه خالی
        self.assertNotIn("dTpzZWNyZXQtcHc", caster.requests[0])  # base64 «u:secret-pw»  # میزبان/درگاه فرق دارد ⇒ بدون گذرواژه ذخیره‌شده
