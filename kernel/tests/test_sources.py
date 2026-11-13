"""ورود دوره‌ای از API بیرونی `[[sources]]`: مشخصات، امنیت واکشی (SSRF)، استخراج، وضعیت/backoff، پنل و مسیر کامل روی PostGIS."""
import datetime
import json
import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

import psycopg
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from databases import services
from databases.tests.test_services import BaseCase
from kernel import crypto, entitlements, notify, pagekit, platform, sources
from kernel.models import PluginUsage, SourceHost, SourceState
from kernel.plugins import registry
from kernel.tests.test_pagekit import STORAGES

PG_HOST = os.environ.get("TEST_PG_HOST", "")
SRC = {"key": "weather", "title": "آب‌وهوا", "url": "https://api.open-meteo.com/v1/forecast", "table": "weather", "layout": "columns",
       "rows_path": "hourly", "cursor": "t", "every_minutes": 60, "since_days": 3,
       "query": {"latitude": "{lat}", "longitude": "{lon}", "hourly": "temperature_2m", "start_date": "{since}", "end_date": "{today}"},
       "inputs": [{"name": "lat", "label": "عرض", "min": -90, "max": 90}, {"name": "lon", "label": "طول", "min": -180, "max": 180}],
       "fields": [{"name": "t", "kind": "text", "label": "زمان", "required": True, "path": "time", "max": 20},
                  {"name": "temp", "kind": "number", "label": "دما", "path": "temperature_2m"}]}
PAGE = {"key": "meteo", "title": "هوا", "need": "editor", "blocks": [{"kind": "text", "text": "x"}], "sources": [SRC]}
RESP = {"hourly": {"time": ["2026-11-10T00:00", "2026-11-10T01:00", "2026-11-10T02:00"], "temperature_2m": [4.5, 3.9, None]}}


def page(**over):
    return pagekit.parse_page("demo", {**PAGE, "sources": [{**SRC, **over}]})


class SpecTests(SimpleTestCase):
    def test_valid(self):
        s = page().sources[0]
        self.assertEqual((s.host, s.path, s.layout, s.every_minutes, s.cursor), ("api.open-meteo.com", "/v1/forecast", "columns", 60, "t"))
        self.assertEqual(dict(s.paths), {"t": "time", "temp": "temperature_2m"})

    def test_rejections(self):
        bad = [{"url": "http://api.x.org/a"}, {"url": "https://127.0.0.1/a"}, {"url": "https://u:p@x.org/a"}, {"url": "https://x.org:8443/a"},
               {"url": "https://x.org/a?k=1"}, {"url": "https://x.org/{a}"}, {"url": "https://localhost/a"}, {"layout": "xml"},
               {"every_minutes": 5}, {"every_minutes": True}, {"since_days": 99}, {"cursor": "nope"}, {"fields": []},
               {"query": {"a": "{unknown}"}}, {"query": {"a": "{lat"}}, {"query": {"bad key": "1"}},
               {"inputs": [{"name": "since", "label": "x"}]}, {"table": "x; drop"},
               {"secret_header": "X-K", "secret_param": "k"}, {"secret_header": "bad header!"},
               {"fields": [{"name": "a", "label": "x", "path": "../../etc"}]}]
        for over in bad:
            with self.subTest(over=over), self.assertRaises(pagekit.SpecError):
                page(**over)
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("demo", {**PAGE, "need": "viewer"})
        with self.assertRaises(pagekit.SpecError):
            pagekit.parse_page("demo", {**PAGE, "sources": [SRC, {**SRC, "key": "b"}, {**SRC, "key": "c"}]})


class FetchSafetyTests(SimpleTestCase):
    def test_private_and_special_addresses_blocked(self):
        for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254", "::1", "fe80::1", "100.64.0.1", "::ffff:127.0.0.1", "0.0.0.0"):
            with self.subTest(ip=ip), mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", (ip, 443))]):
                with self.assertRaises(sources.SourceError):
                    sources._public_ip("x.org")

    def test_any_private_among_answers_blocks(self):
        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("10.0.0.1", 443))]):
            with self.assertRaises(sources.SourceError):
                sources._public_ip("x.org")

    def test_public_ok_and_unresolvable(self):
        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
            self.assertEqual(sources._public_ip("x.org"), "93.184.216.34")
        with mock.patch("socket.getaddrinfo", side_effect=OSError):
            with self.assertRaises(sources.SourceError):
                sources._public_ip("x.org")

    def test_fetch_pins_checked_ip_and_hides_details(self):
        fake = mock.Mock()
        fake.getresponse.return_value = mock.Mock(status=200, read=lambda n: b"{}")
        with mock.patch.object(sources, "_public_ip", return_value="93.184.216.34"), mock.patch.object(sources, "_Pinned", return_value=fake) as cls:
            self.assertEqual(sources._fetch("x.org", "/a?b=1", {"X-K": "v"}), b"{}")
        cls.assert_called_once_with("x.org", "93.184.216.34")
        fake.request.assert_called_once()
        self.assertEqual(fake.request.call_args.args[:2], ("GET", "/a?b=1"))

    def test_fetch_status_oversize_and_network_errors(self):
        def conn(status=200, body=b"{}", exc=None):
            c = mock.Mock()
            if exc:
                c.request.side_effect = exc
            c.getresponse.return_value = mock.Mock(status=status, read=lambda n: body)
            return c
        for c, msg in ((conn(status=302), "302"), (conn(body=b"x" * (sources.MAX_BYTES + 1)), "بزرگ"), (conn(exc=OSError("secret path /etc")), "اتصال")):
            with self.subTest(msg=msg), mock.patch.object(sources, "_public_ip", return_value="93.184.216.34"), mock.patch.object(sources, "_Pinned", return_value=c):
                with self.assertRaises(sources.SourceError) as cm:
                    sources._fetch("x.org", "/", {})
            self.assertIn(msg, str(cm.exception))
            self.assertNotIn("secret path", str(cm.exception))


class ExtractTests(SimpleTestCase):
    def setUp(self):
        self.spec = page().sources[0]

    def test_columns_layout_and_cursor_filter(self):
        raw = sources.extract(self.spec, RESP)
        self.assertEqual(len(raw), 3)
        rows, bad, newest = sources.convert(self.spec, raw, "")
        self.assertEqual((len(rows), bad, newest), (3, 0, "2026-11-10T02:00"))
        self.assertEqual(rows[0], {"t": "2026-11-10T00:00", "temp": 4.5})
        self.assertIsNone(rows[2]["temp"])
        rows, _, newest = sources.convert(self.spec, raw, "2026-11-10T01:00")
        self.assertEqual([r["t"] for r in rows], ["2026-11-10T02:00"])
        self.assertEqual(newest, "2026-11-10T02:00")

    def test_rows_layout(self):
        s = page(layout="rows", rows_path="data.items", cursor="").sources[0]
        data = {"data": {"items": [{"time": "a", "temperature_2m": 1}, {"time": "b", "temperature_2m": "x"}, "junk"]}}
        rows, bad, _ = sources.convert(s, sources.extract(s, data), "")
        self.assertEqual((len(rows), bad), (1, 1))  # ردیف نامعتبر رد می‌شود

    def test_structure_mismatch(self):
        for data in ({}, {"hourly": []}, {"hourly": {"time": [1]}}, [], "x", {"hourly": {"time": "a", "temperature_2m": "b"}}):
            with self.subTest(data=data), self.assertRaises(sources.SourceError):
                sources.extract(self.spec, data)

    def test_caps_rows(self):
        big = {"hourly": {"time": [str(i) for i in range(sources.MAX_ROWS + 50)], "temperature_2m": [1] * (sources.MAX_ROWS + 50)}}
        self.assertEqual(len(sources.extract(self.spec, big)), sources.MAX_ROWS)

    def test_nested_value_is_invalid(self):
        rows, bad, _ = sources.convert(self.spec, [{"t": "a", "temp": {"x": 1}}], "")
        self.assertEqual((rows, bad), ([], 1))


class RequestTests(TestCase):
    def setUp(self):
        self.spec = page().sources[0]
        self.now = timezone.now()

    def st(self, **kw):
        return SourceState(plugin_id="demo", page="meteo", key="weather", workspace_id=1, inputs={"lat": "35.7", "lon": "51.4"}, **kw)

    def test_placeholders_and_since(self):
        target, headers = sources.build_request(self.spec, self.st(), self.now)
        q = dict(p.split("=") for p in target.split("?")[1].split("&"))
        self.assertEqual((q["latitude"], q["longitude"]), ("35.7", "51.4"))
        self.assertEqual(q["start_date"], (timezone.localtime(self.now).date() - datetime.timedelta(days=3)).isoformat())
        self.assertEqual(headers, {})
        target, _ = sources.build_request(self.spec, self.st(cursor="2026-11-10T02:00"), self.now)
        self.assertIn("start_date=2026-11-10", target)

    def test_inputs_validated_and_encoded(self):
        for bad in ({"lat": "999", "lon": "1"}, {"lat": "x", "lon": "1"}, {"lat": "", "lon": "1"}):
            st = self.st()
            st.inputs = bad
            with self.subTest(bad=bad), self.assertRaises(sources.SourceError):
                sources.build_request(self.spec, st, self.now)
        s = page(inputs=[{"name": "q", "label": "x", "kind": "text"}], query={"q": "{q}"}, fields=SRC["fields"], cursor="").sources[0]
        st = self.st()
        st.inputs = {"q": "a&b=c d"}
        self.assertEqual(sources.build_request(s, st, self.now)[0], "/v1/forecast?q=a%26b%3Dc+d")

    def test_secret_header_and_param(self):
        s = page(secret_header="X-Api-Key").sources[0]
        with self.assertRaises(sources.SourceError):
            sources.build_request(s, self.st(), self.now)
        _, h = sources.build_request(s, self.st(secret_enc=crypto.encrypt("K123")), self.now)
        self.assertEqual(h, {"X-Api-Key": "K123"})
        s = page(secret_param="apikey").sources[0]
        self.assertIn("apikey=K123", sources.build_request(s, self.st(secret_enc=crypto.encrypt("K123")), self.now)[0])


class RunTests(TestCase):
    def setUp(self):
        registry.register("demo", "نمونه", kind="custom")
        self.addCleanup(registry.remove_plugin, "demo")
        self.addCleanup(entitlements.invalidate)
        self.page = pagekit.parse_page("demo", PAGE)
        self.spec = self.page.sources[0]
        self.owner = get_user_model().objects.create_user(username="o", phone="09120000777", password="x")
        self.ws = SimpleNamespace(pk=5, owner=self.owner, is_live=True)
        self.st = SourceState.objects.create(plugin_id="demo", page="meteo", key="weather", workspace_id=5, enabled=True,
                                             inputs={"lat": "35.7", "lon": "51.4"}, next_run=timezone.now())
        platform.set_("sources_enabled", "1")
        self.addCleanup(platform.invalidate)
        SourceHost.objects.create(host="api.open-meteo.com")
        self.inserted = []
        self.fetch = mock.Mock(return_value=json.dumps(RESP).encode())
        for target, val in (("kernel.sources._fetch", self.fetch), ("kernel.pagekit.insert_rows", lambda ws, spec, rows: self.inserted.append(rows)),
                            ("kernel.tables.ensure", lambda *a: 0)):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)

    def run_(self, now=None):
        self.st.refresh_from_db()
        return sources.run_one(self.st, self.page, self.spec, self.ws, now)

    def test_success_updates_state_cursor_and_metering(self):
        self.assertEqual(self.run_(), "")
        self.st.refresh_from_db()
        self.assertEqual((self.st.cursor, self.st.last_rows, self.st.fails, self.st.last_error), ("2026-11-10T02:00", 3, 0, ""))
        self.assertEqual(len(self.inserted[0]), 3)
        self.assertEqual(PluginUsage.objects.get(metric="source_rows").count, 3)
        self.assertEqual(PluginUsage.objects.get(metric="source_fetches").count, 1)
        self.fetch.reset_mock()
        self.assertEqual(self.run_(), "")  # دومی: ردیف تازه ندارد
        self.assertEqual(len(self.inserted), 1)

    def test_switch_off_unapproved_host_and_cap(self):
        platform.set_("sources_enabled", "")
        self.assertIn("خاموش", self.run_())
        platform.set_("sources_enabled", "1")
        SourceHost.objects.all().delete()
        self.assertIn("تأیید نشده", self.run_())
        self.fetch.assert_not_called()
        SourceHost.objects.create(host="api.open-meteo.com")
        with mock.patch("kernel.metering.check", return_value=(False, 99, 99)):
            self.assertIn("سقف", self.run_())

    def test_failure_backoff_then_auto_disable_and_owner_notified(self):
        self.fetch.side_effect = sources.SourceError("اتصال به سرویس بیرونی برقرار نشد.")
        now = timezone.now()
        with mock.patch.object(notify, "deliver") as dl:
            for n in range(1, sources.MAX_FAILS):
                self.assertTrue(self.run_(now))
                self.st.refresh_from_db()
                self.assertEqual(self.st.fails, n)
                self.assertEqual(self.st.next_run, now + datetime.timedelta(minutes=min(60 * 2 ** (n - 1), sources.MAX_BACKOFF_MIN)))
                self.assertTrue(self.st.enabled)
            dl.assert_not_called()
            self.run_(now)
            self.st.refresh_from_db()
            self.assertFalse(self.st.enabled)
            dl.assert_called_once()
            self.assertIs(dl.call_args.args[0], self.owner)

    def test_bad_json_and_all_rows_invalid(self):
        self.fetch.return_value = b"<html>secret</html>"
        err = self.run_()
        self.assertIn("JSON", err)
        self.assertNotIn("secret", err)
        self.fetch.return_value = json.dumps({"hourly": {"time": [None, None], "temperature_2m": [1, 2]}}).encode()
        self.assertIn("ردیف معتبر", self.run_())

    def test_database_failure_is_generic(self):
        with mock.patch("kernel.pagekit.insert_rows", side_effect=RuntimeError("password=hunter2 host=10.0.0.9")):
            err = self.run_()
        self.assertNotIn("hunter2", err)
        self.assertIn("نوشتن", err)

    def test_success_resets_fails(self):
        SourceState.objects.filter(pk=self.st.pk).update(fails=3)
        self.assertEqual(self.run_(), "")
        self.st.refresh_from_db()
        self.assertEqual(self.st.fails, 0)

    def test_tick_runs_due_only_and_respects_switch_and_access(self):
        with mock.patch("kernel.pagekit.get", lambda p, k: self.page), \
                mock.patch("kernel.workspace.peek", lambda pk: self.ws):
            self.assertEqual(sources.tick()["ran"], 1)
            self.assertEqual(sources.tick()["ran"], 0)  # next_run در آینده
            SourceState.objects.update(next_run=timezone.now() - datetime.timedelta(minutes=1))
            platform.set_("sources_enabled", "")
            self.assertTrue(sources.tick().get("off"))
            platform.set_("sources_enabled", "1")
            from kernel.models import PluginState
            PluginState.objects.create(plugin_id="demo", access="restricted")
            entitlements.invalidate()
            self.assertEqual(sources.tick()["ran"], 0)  # مجوز ندارد

    def test_run_now_rate_limited(self):
        with mock.patch("kernel.entitlements.allowed", return_value=True):
            self.assertEqual(sources.run_now(self.ws, "demo", self.page, self.spec), "")
            self.assertIn("۵ دقیقه", sources.run_now(self.ws, "demo", self.page, self.spec))

    def test_configure_encrypts_key_and_validates(self):
        s = page(secret_header="X-K").sources[0]
        with self.assertRaises(ValueError):
            sources.configure(self.ws, "demo", self.page, s, {"i_lat": "1", "i_lon": "2"}, enable=True)  # بدون کلید
        with self.assertRaises(ValueError):
            sources.configure(self.ws, "demo", self.page, s, {"i_lat": "999", "i_lon": "2", "secret": "k"}, enable=True)
        st = sources.configure(self.ws, "demo", self.page, s, {"i_lat": "1", "i_lon": "2", "secret": "TOPSECRET"}, enable=True)
        self.assertNotIn("TOPSECRET", st.secret_enc)
        self.assertTrue(st.enabled)
        st = sources.configure(self.ws, "demo", self.page, s, {"i_lat": "3", "i_lon": "2"}, enable=True)  # کلید خالی = بدون تغییر
        self.assertEqual(crypto.decrypt(st.secret_enc), "TOPSECRET")


class AdminTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="adm", phone="09120000101", password="x")
        self.client.force_login(self.admin)
        self.addCleanup(platform.invalidate)

    def test_host_add_validate_and_switch(self):
        url = reverse("admin:kernel_sourcehost_add")
        for bad in ("https://api.x.org/a", "127.0.0.1", "*.x.org", "localhost", "x_y.org"):
            self.assertEqual(self.client.post(url, {"host": bad, "note": ""}).status_code, 200, bad)
        self.assertFalse(SourceHost.objects.exists())
        self.assertEqual(self.client.post(url, {"host": "API.Open-Meteo.com", "note": "هوا"}).status_code, 302)
        self.assertTrue(SourceHost.objects.filter(host="api.open-meteo.com", added_by=self.admin).exists())
        self.assertFalse(platform.sources_enabled())
        self.client.post(reverse("admin:kernel_publisherkey_changelist"), {"action": "save_sources", "sources_enabled": "1"})
        platform.invalidate()
        self.assertTrue(platform.sources_enabled())

    def test_state_admin_hides_key(self):
        SourceState.objects.create(plugin_id="d", page="p", key="k", workspace_id=1, secret_enc=crypto.encrypt("ZZZ-SECRET"), last_error="x")
        r = self.client.get(reverse("admin:kernel_sourcestate_changelist"))
        self.assertNotContains(r, "ZZZ-SECRET")
        r = self.client.get(reverse("admin:kernel_sourcestate_change", args=[SourceState.objects.get().pk]))
        self.assertNotContains(r, "ZZZ-SECRET")
        self.assertNotContains(r, "gAAAA")


@override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10)
class ViewTests(BaseCase):
    def setUp(self):
        super().setUp()
        registry.register("demo", "نمونه", kind="custom")
        self.addCleanup(registry.remove_plugin, "demo")
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(platform.invalidate)
        self.page = pagekit.parse_page("demo", PAGE)
        p = mock.patch("kernel.pagekit.get", lambda a, b: self.page if (a, b) == ("demo", "meteo") else None)
        p.start()
        self.addCleanup(p.stop)
        self.db = services.create_database(self.user, "tehran", "Abcdefgh123", ["postgis"])
        self.client.force_login(self.user)
        self.args = [self.db.pk, "demo", "meteo", "weather"]

    def test_non_owner_cannot_configure(self):
        other = get_user_model().objects.create_user(username="x2", phone="09120000555", password="x")
        self.client.force_login(other)
        r = self.client.post(reverse("kernel:source_save", args=self.args), {"do": "enable", "i_lat": "1", "i_lon": "2"})
        self.assertIn(r.status_code, (403, 404))
        self.assertFalse(SourceState.objects.exists())

    def test_owner_enable_disable_and_run(self):
        r = self.client.post(reverse("kernel:source_save", args=self.args), {"do": "enable", "i_lat": "35.7", "i_lon": "51.4"})
        self.assertEqual(r.status_code, 302)
        st = SourceState.objects.get()
        self.assertTrue(st.enabled)
        self.client.post(reverse("kernel:source_save", args=self.args), {"do": "enable", "i_lat": "999", "i_lon": "51.4"})
        st.refresh_from_db()
        self.assertEqual(st.inputs["lat"], "35.7")  # ورودی نامعتبر ذخیره نشد
        with mock.patch("kernel.sources.run_now", return_value="") as rn:
            self.client.post(reverse("kernel:source_run", args=self.args))
            rn.assert_called_once()
        self.client.post(reverse("kernel:source_save", args=self.args), {"do": "disable"})
        st.refresh_from_db()
        self.assertFalse(st.enabled)

    def test_unknown_source_404(self):
        r = self.client.post(reverse("kernel:source_save", args=[self.db.pk, "demo", "meteo", "nope"]), {"do": "enable"})
        self.assertEqual(r.status_code, 404)

    def test_page_shows_warnings_and_card(self):
        with mock.patch("kernel.pages_view.pagekit.render_block", return_value={"kind": "text", "text": "x", "width": "full"}):
            r = self.client.get(reverse("kernel:page", args=[self.db.pk, "demo", "meteo"]))
        self.assertContains(r, 'id="source-weather"')
        self.assertContains(r, "هنوز روشن نکرده")
        self.assertContains(r, 'name="i_lat"')


@unittest.skipUnless(PG_HOST, "به PostgreSQL آزمون نیاز دارد (TEST_PG_HOST)")
@override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10)
class RealChainTests(BaseCase):
    """زنجیره‌ی کامل روی PostgreSQL واقعی: پاسخ (mock) ← جدول مشتری؛ دومین اجرا ردیف تکراری نمی‌نویسد."""

    def setUp(self):
        super().setUp()
        registry.register("demo", "نمونه", kind="custom")
        self.addCleanup(registry.remove_plugin, "demo")
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(platform.invalidate)
        self.kw = dict(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=os.environ.get("TEST_PG_USER", "postgres"),
                       password=os.environ.get("TEST_PG_PASSWORD", "postgres"), autocommit=True)
        with psycopg.connect(dbname="postgres", **self.kw) as c:
            c.execute("DROP DATABASE IF EXISTS pagekit_src")
            c.execute("CREATE DATABASE pagekit_src")
        with psycopg.connect(dbname="pagekit_src", **self.kw) as c:
            c.execute("CREATE TABLE weather (id serial primary key, t text not null, temp double precision)")
        cat = mock.Mock()
        cat.tables.return_value = [SimpleNamespace(schema="public", name="weather", kind="r", oid=0)]
        cat.columns.return_value = [{"name": n, "generated": False, "identity": "", "spatial": False} for n in ("t", "temp")]
        kw = self.kw

        @contextmanager
        def connect(ws, **kw2):
            conn = psycopg.connect(dbname="pagekit_src", **kw)
            conn.autocommit = False
            try:
                yield conn
            finally:
                conn.close()

        for target, val in (("kernel.tenantdb.catalog", lambda ws: cat), ("kernel.tenantdb.connect", connect)):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)
        platform.set_("sources_enabled", "1")
        SourceHost.objects.create(host="api.open-meteo.com")
        self.page = pagekit.parse_page("demo", PAGE)
        self.spec = self.page.sources[0]
        self.ws = SimpleNamespace(pk=9, owner=self.user, is_live=True)
        self.st = SourceState.objects.create(plugin_id="demo", page="meteo", key="weather", workspace_id=9, enabled=True,
                                             inputs={"lat": "35.7", "lon": "51.4"})

    def rows(self):
        with psycopg.connect(dbname="pagekit_src", **self.kw) as c:
            return c.execute("SELECT t, temp FROM weather ORDER BY id").fetchall()

    def test_chain_and_incremental(self):
        with mock.patch.object(sources, "_fetch", return_value=json.dumps(RESP).encode()):
            self.assertEqual(sources.run_one(self.st, self.page, self.spec, self.ws), "")
            self.assertEqual(self.rows(), [("2026-11-10T00:00", 4.5), ("2026-11-10T01:00", 3.9), ("2026-11-10T02:00", None)])
            self.assertEqual(sources.run_one(self.st, self.page, self.spec, self.ws), "")
        self.assertEqual(len(self.rows()), 3)  # بدون تکرار
        more = {"hourly": {"time": ["2026-11-10T02:00", "2026-11-10T03:00"], "temperature_2m": [1, 2.5]}}
        with mock.patch.object(sources, "_fetch", return_value=json.dumps(more).encode()):
            sources.run_one(self.st, self.page, self.spec, self.ws)
        self.assertEqual(self.rows()[-1], ("2026-11-10T03:00", 2.5))
        self.assertEqual(len(self.rows()), 4)

    def test_constraint_failure_writes_nothing_and_cursor_stays(self):
        with psycopg.connect(dbname="pagekit_src", **self.kw) as c:
            c.execute("ALTER TABLE weather ADD CONSTRAINT lim CHECK (temp is null or temp < 4)")
        with mock.patch.object(sources, "_fetch", return_value=json.dumps(RESP).encode()):
            err = sources.run_one(self.st, self.page, self.spec, self.ws)
        self.assertTrue(err)
        self.assertEqual(self.rows(), [])
        self.st.refresh_from_db()
        self.assertEqual((self.st.cursor, self.st.fails), ("", 1))


@unittest.skipUnless(PG_HOST, "به PostgreSQL آزمون نیاز دارد (TEST_PG_HOST)")
@override_settings(STORAGES=STORAGES, MAX_DATABASES_PER_USER=10)
class WeatherReplaceTests(BaseCase):
    """منبع هواشناسی نمونه روی PostgreSQL واقعی: حالت replace پنجره‌ی هم‌پوشان همان مکان/مدل را به‌روز می‌کند و بقیه را نگه می‌دارد."""

    def setUp(self):
        super().setUp()
        import tomllib

        from kernel import samples, tables
        registry.register(samples.WEATHER_ID, "هوا", kind="custom")
        self.addCleanup(registry.remove_plugin, samples.WEATHER_ID)
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(platform.invalidate)
        self.page = pagekit.parse_page(samples.WEATHER_ID, tomllib.loads(samples.page_text(samples.WEATHER_ID)))
        self.spec = self.page.sources[0]
        kw = dict(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=os.environ.get("TEST_PG_USER", "postgres"),
                  password=os.environ.get("TEST_PG_PASSWORD", "postgres"), autocommit=True)
        self.kw = kw
        with psycopg.connect(dbname="postgres", **kw) as c:
            c.execute("DROP DATABASE IF EXISTS pagekit_wx")
            c.execute("CREATE DATABASE pagekit_wx")
        with psycopg.connect(dbname="pagekit_wx", **kw) as c:
            c.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            for t in self.page.tables:
                c.execute(tables.create_statement(t))
        t0 = self.page.tables[0]
        cat = mock.Mock()
        cat.tables.return_value = [SimpleNamespace(schema="public", name=t.name, kind="r", oid=i) for i, t in enumerate(self.page.tables)]
        cat.columns.side_effect = lambda table: [{"name": c.name, "type": "x", "generated": False, "identity": "", "spatial": False, "pk": False}
                                                 for c in t0.columns] + [{"name": "id", "type": "bigint", "generated": False, "identity": "", "spatial": False, "pk": True}]

        @contextmanager
        def connect(ws, **k):
            conn = psycopg.connect(dbname="pagekit_wx", **kw)
            conn.autocommit = False
            try:
                yield conn
            finally:
                conn.close()

        for target, val in (("kernel.tenantdb.catalog", lambda ws: cat), ("kernel.tenantdb.connect", connect), ("kernel.tables.ensure", lambda *a: 0)):
            p = mock.patch(target, val)
            p.start()
            self.addCleanup(p.stop)
        platform.set_("sources_enabled", "1")
        SourceHost.objects.create(host="api.open-meteo.com")
        self.ws = SimpleNamespace(pk=11, owner=self.user, is_live=True)

    def state(self, **inputs):
        base = {"lat": "35.7", "lon": "51.4", "variables": ["temperature_2m", "wind_speed_10m"], "model": "ecmwf_ifs025", "days": "3"}
        SourceState.objects.filter(workspace_id=11).delete()
        return SourceState.objects.create(plugin_id=self.page.plugin, page="meteo", key="forecast", workspace_id=11, enabled=True, inputs={**base, **inputs})

    def rows(self):
        with psycopg.connect(dbname="pagekit_wx", **self.kw) as c:
            return c.execute("SELECT t, model, lat, temperature_2m, wind_speed_10m, relative_humidity_2m FROM weather_online_forecast ORDER BY model, t").fetchall()

    def resp(self, times, temps):
        return json.dumps({"hourly": {"time": times, "temperature_2m": temps, "wind_speed_10m": [5.0] * len(times)}}).encode()

    def test_replace_updates_overlap_keeps_other_models(self):
        st = self.state()
        with mock.patch.object(sources, "_fetch", return_value=self.resp(["2026-11-13T00:00", "2026-11-13T01:00"], [10.0, 11.0])):
            self.assertEqual(sources.run_one(st, self.page, self.spec, self.ws), "")
        self.assertEqual(self.rows(), [("2026-11-13T00:00", "ecmwf_ifs025", 35.7, 10.0, 5.0, None), ("2026-11-13T01:00", "ecmwf_ifs025", 35.7, 11.0, 5.0, None)])
        # پیش‌بینی تازه: ساعت اول عوض شد، ساعت سوم تازه؛ ردیف قبلی بدون تکرار جایگزین می‌شود
        with mock.patch.object(sources, "_fetch", return_value=self.resp(["2026-11-13T01:00", "2026-11-13T02:00"], [12.5, 13.0])):
            self.assertEqual(sources.run_one(st, self.page, self.spec, self.ws), "")
        got = self.rows()
        self.assertEqual([(r[0], r[3]) for r in got], [("2026-11-13T00:00", 10.0), ("2026-11-13T01:00", 12.5), ("2026-11-13T02:00", 13.0)])
        # مدل دیگر هم‌زمان کنار می‌ماند و ردیف‌های مدل اول را پاک نمی‌کند
        st2 = self.state(model="gfs_seamless")
        SourceState.objects.filter(pk=st2.pk).update(cursor="")
        with mock.patch.object(sources, "_fetch", return_value=self.resp(["2026-11-13T01:00"], [9.0])):
            sources.run_one(st2, self.page, self.spec, self.ws)
        by_model = {}
        for r in self.rows():
            by_model.setdefault(r[1], []).append(r[3])
        self.assertEqual(by_model, {"ecmwf_ifs025": [10.0, 12.5, 13.0], "gfs_seamless": [9.0]})

    def test_unselected_variable_is_null_and_bad_response_writes_nothing(self):
        st = self.state()
        with mock.patch.object(sources, "_fetch", return_value=self.resp(["2026-11-13T00:00"], [1.0])):
            sources.run_one(st, self.page, self.spec, self.ws)
        self.assertIsNone(self.rows()[0][5])  # رطوبت انتخاب نشده بود
        st = self.state()
        bad = json.dumps({"hourly": {"time": ["2026-11-13T05:00"]}}).encode()  # بدون هیچ متغیری
        with mock.patch.object(sources, "_fetch", return_value=bad):
            err = sources.run_one(st, self.page, self.spec, self.ws)
        self.assertTrue(err)
