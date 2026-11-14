"""منابع ماهواره در پنل: تنظیم از پنل، پیکربندی دروازه (۴۰۹ ← ارسال دوباره)، سهمیه‌ی مشترک با وزن، پلن و صفحه‌ی مدیریت."""
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from databases.models import DatabaseServer, Plan, UserDatabase
from kernel import conf
from satellite import client, probe, services, sources
from satellite.models import SatRequest
from satgate import protocol, spec

BBOX = [51.30, 35.70, 51.34, 35.73]
GW = override_settings(SATGATE_URL="https://gw.test", SATGATE_SECRET="s3cret")


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        sources.invalidate()
        self.addCleanup(sources.invalidate)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.server = DatabaseServer(name="s1", host="10.0.0.5", public_host="db.postgis.ir", is_default=True)
        self.server.set_admin_password("secret")
        self.server.save()
        self.user = User.objects.create_user("09120000091")
        self.plan = Plan.objects.create(name="ماهواره", slug="sat-p", is_free=False, price_toman=1, raster_mb=4096, sat_credits=10,
                                        sat_max_km2=500)
        self.db = UserDatabase.objects.create(owner=self.user, server=self.server, plan=self.plan, label="s", db_name="gp_s",
                                              role_name="gp_s_user", status=UserDatabase.Status.ACTIVE)

    def set(self, **values):
        for k, v in values.items():
            conf.set_value(sources.PLUGIN, k, v)
        sources.invalidate()


class OptionsTests(_Base):
    def test_every_provider_and_mission_declares_options(self):
        keys = {o.key for o in conf.options(sources.PLUGIN)}
        for m in spec.MISSIONS:
            self.assertTrue({f"m_{m}_enabled", f"m_{m}_weight", f"m_{m}_max_km2"} <= keys, m)
        for p in spec.PROVIDERS.values():
            self.assertIn(f"prov_{p.key}_enabled", keys)
            for name, _, _ in p.creds:
                self.assertIn(f"prov_{p.key}_{name}", keys)
        self.assertIn("m_sentinel2_prefer", keys)
        self.assertNotIn("m_landsat_prefer", keys)                           # تنها یک منبع دارد
        self.assertTrue(all(len(k) <= 60 for k in keys))                    # ستون key در PluginSetting

    def test_defaults_and_get_all(self):
        v = conf.get_all(sources.PLUGIN)
        self.assertTrue(v["m_sentinel2_enabled"])
        self.assertEqual(v["m_s1_rtc_weight"], 2)                            # رادار پیش‌فرض دو واحد
        self.assertEqual(v["m_sentinel2_prefer"], "earthsearch")
        self.set(m_landsat_weight=3)
        self.assertEqual(conf.get_all(sources.PLUGIN)["m_landsat_weight"], 3)
        self.assertEqual(sources.weight("landsat"), 3)


class ConfigDocTests(_Base):
    def test_build_config_has_all_keys_and_only_set_credentials(self):
        self.set(prov_copernicus_s3_access="AK123", prov_copernicus_s3_secret="SK456", m_landsat_enabled=False,
                 prov_planetary_url="https://pc.example.org/api")
        doc = sources.build_config()
        self.assertEqual(set(doc["missions"]), set(spec.MISSIONS))
        self.assertEqual(set(doc["providers"]), set(spec.PROVIDERS))
        self.assertEqual(doc["providers"]["copernicus"]["cred"], {"s3_access": "AK123", "s3_secret": "SK456"})
        self.assertNotIn("cred", doc["providers"]["earthsearch"])
        self.assertEqual(doc["providers"]["planetary"]["url"], "https://pc.example.org/api")
        self.assertFalse(doc["missions"]["landsat"]["enabled"])
        self.assertEqual(doc["missions"]["sentinel2"]["prefer"], "earthsearch")

    def test_the_gateway_accepts_what_the_panel_builds(self):
        from satgate.runtime import RUNTIME
        self.addCleanup(RUNTIME.reset)
        self.set(prov_opentopography_api_key="KEY", m_dem_prefer="planetary", m_water_max_km2=50)
        doc = sources.build_config()
        self.assertEqual(RUNTIME.apply(doc), protocol.config_hash(doc))

    def test_secrets_never_reach_the_cache(self):
        self.set(prov_copernicus_s3_secret="VERY-SECRET-VALUE", prov_earthdata_password="PW-VALUE")
        sources.config_hash()
        blob = json.dumps(cache.get(sources.CACHE_KEY))
        self.assertNotIn("VERY-SECRET-VALUE", blob)
        self.assertNotIn("PW-VALUE", blob)
        self.assertEqual(sources.provider_state("copernicus")["creds"], ["s3_secret"])        # فقط «تنظیم شده»

    def test_long_token_is_stored_and_reaches_the_gateway_document(self):
        jwt = "eyJ0eXAiOiJKV1Qi" + "B" * 1600
        self.set(prov_earthdata_token=jwt)
        self.assertEqual(sources.build_config()["providers"]["earthdata"]["cred"], {"token": jwt})
        from satgate.runtime import RUNTIME
        self.addCleanup(RUNTIME.reset)
        RUNTIME.apply(sources.build_config())
        self.assertEqual(RUNTIME.cred("earthdata", "token"), jwt)

    def test_hash_changes_with_settings_and_is_cached_until_invalidated(self):
        h1 = sources.config_hash()
        conf.set_value(sources.PLUGIN, "m_landsat_enabled", False)          # بدون invalidate: کش
        self.assertEqual(sources.config_hash(), h1)
        sources.invalidate()
        self.assertNotEqual(sources.config_hash(), h1)

    def test_plan_missions(self):
        self.assertIsNone(sources.plan_missions(self.plan))
        self.plan.sat_missions = " sentinel2 ,dem،nope"
        self.assertEqual(sources.plan_missions(self.plan), {"sentinel2", "dem"})
        self.assertTrue(sources.plan_allows(self.plan, "dem"))
        self.assertFalse(sources.plan_allows(self.plan, "landsat"))


@GW
class ClientConfigTests(_Base):
    def test_job_and_search_carry_the_config_hash(self):
        with mock.patch("satellite.client._call", return_value={"ok": True}) as c:
            client.call("POST", "/v1/jobs", {"id": "x"})
            client.call("POST", "/v1/search", {"bbox": BBOX})
            client.call("GET", "/v1/missions")
            client.call("POST", "/v1/probe", {})
        sent = [x.args[2] for x in c.call_args_list]
        self.assertEqual(sent[0]["cfg"], sources.config_hash())
        self.assertEqual(sent[1]["cfg"], sources.config_hash())
        self.assertNotIn("cfg", sent[3] or {})                                # فقط کار و جست‌وجو و تحلیل

    def test_409_makes_the_panel_push_config_and_retry_once(self):
        stale = client.GatewayError("قدیمی", 409, "config")
        calls = []

        def fake(method, path, data, timeout):
            calls.append((method, path))
            if path == "/v1/config":
                return {"ok": True, "hash": protocol.config_hash(data)}
            if len([c for c in calls if c[1] == "/v1/jobs"]) == 1:
                raise stale
            return {"id": "x", "status": "queued"}
        with mock.patch("satellite.client._call", side_effect=fake):
            self.assertEqual(client.call("POST", "/v1/jobs", {"id": "x"})["status"], "queued")
        self.assertEqual(calls, [("POST", "/v1/jobs"), ("PUT", "/v1/config"), ("POST", "/v1/jobs")])

    def test_other_errors_are_not_retried_and_failed_push_is_reported(self):
        with mock.patch("satellite.client._call", side_effect=client.GatewayError("پر است", 503)) as c, self.assertRaises(client.GatewayError):
            client.call("POST", "/v1/jobs", {"id": "x"})
        self.assertEqual(c.call_count, 1)

        def fake(method, path, data, timeout):
            if path == "/v1/config":
                raise client.GatewayError("پیدا نشد", 404)
            raise client.GatewayError("قدیمی", 409, "config")
        with mock.patch("satellite.client._call", side_effect=fake), self.assertRaises(client.GatewayError) as e:
            client.call("POST", "/v1/jobs", {"id": "x"})
        self.assertIn("به‌روز", str(e.exception))

    def test_push_checks_the_returned_hash(self):
        with mock.patch("satellite.client._call", return_value={"ok": True, "hash": "other"}):
            ok, msg = sources.push()
        self.assertFalse(ok)
        self.assertIn("چکیده", msg)
        with mock.patch("satellite.client._call", side_effect=lambda m, p, d, t: {"ok": True, "hash": protocol.config_hash(d)}):
            self.assertTrue(sources.push()[0])
        with mock.patch("satellite.client._call", side_effect=client.GatewayError("x", 404)):
            ok, msg = sources.push()
        self.assertFalse(ok)
        self.assertIn("قدیمی", msg)


@GW
class QuoteAndCreditsTests(_Base):
    def quote(self, product="ndvi", mission="sentinel2", db=None):
        return services.quote(db or self.db, BBOX, product, mission)

    def codes(self, q):
        return [b["code"] for b in q["blockers"]]

    def test_cost_comes_from_mission_weight_and_is_charged_as_units(self):
        self.assertEqual(self.quote()["cost"], 1)
        self.set(m_s1_rtc_weight=4)
        q = self.quote("vv_db", "s1_rtc")
        self.assertEqual((q["cost"], q["ok"]), (4, True))
        with mock.patch("satellite.client.call", return_value={}):
            r = services.order(self.db, self.user, {"bbox": BBOX, "product": "vv_db", "mission": "s1_rtc", "scene": "S1A_IW_ONE",
                                                    "scene_date": "2026-06-01T03:00:00Z", "source": "planetary", "mask": True})
        self.assertEqual((r.credit_cost, r.mask), (4, False))                # رادار ماسک ابر ندارد
        self.assertEqual(services.credits(self.db)["used"], 4)
        self.set(m_s1_rtc_weight=7)
        q = self.quote("vv_db", "s1_rtc")                                    # ۶ واحد مانده و ۷ می‌خواهد
        self.assertIn("credits", self.codes(q))
        self.assertIn("۷ واحد", q["blockers"][0]["message"])

    def test_credits_sum_weights_of_all_missions(self):
        for i, w in enumerate((1, 2, 3)):
            SatRequest.objects.create(database=self.db, user=self.user, product="ndvi", scene_id=f"S2A_{i}_X", bbox=BBOX, credit_cost=w)
        self.assertEqual(services.credits(self.db)["used"], 6)
        self.assertEqual(services.credits(self.db)["left"], 4)
        SatRequest.objects.filter(scene_id="S2A_2_X").update(charged=False)       # ناموفق: اعتبار برمی‌گردد
        self.assertEqual(services.credits(self.db)["used"], 3)

    def test_disabled_mission_and_plan_restriction_block_with_reason(self):
        self.set(m_landsat_enabled=False)
        self.assertIn("mission_off", self.codes(self.quote(mission="landsat")))
        self.plan.sat_missions = "sentinel2"
        self.plan.save()
        self.db.refresh_from_db()
        q = self.quote("ndvi", "s2_c1")
        self.assertIn("mission_plan", self.codes(q))
        self.assertIn("upgrade", q["blockers"][0]["fix"])
        self.assertTrue(self.quote()["ok"])

    def test_panel_area_cap_is_lower_of_plan_and_mission(self):
        big = [51.0, 35.0, 51.3, 35.3]                                        # حدود ۹۰۰ کیلومتر مربع؛ پلن ۵۰۰
        self.assertIn("area", self.codes(services.quote(self.db, big, "ndvi", "sentinel2")))
        self.plan.sat_max_km2 = 2000
        self.plan.save()
        self.db.refresh_from_db()
        self.assertNotIn("area", self.codes(services.quote(self.db, big, "ndvi", "sentinel2")))
        self.set(m_sentinel2_max_km2=300)
        self.assertIn("area", self.codes(services.quote(self.db, big, "ndvi", "sentinel2")))

    def test_layers_need_no_scene_and_old_dem_product_still_works(self):
        for product, mission in (("dem90", "dem90"), ("worldcover", "worldcover"), ("water", "water"), ("nasadem", "nasadem")):
            self.assertTrue(self.quote(product, mission)["ok"], product)
        old = services.quote(self.db, BBOX, "dem", "sentinel2")               # رابط قدیمی: محصول dem با هر ماهواره
        self.assertEqual(old["mission"], "dem")
        with mock.patch("satellite.client.call", return_value={}) as call:
            r = services.order(self.db, self.user, {"bbox": BBOX, "product": "worldcover", "mission": "worldcover"})
        self.assertEqual((r.mission, r.scene_id), ("worldcover", "esa-worldcover"))
        self.assertEqual(call.call_args.args[2]["mission"], "worldcover")

    def test_l1c_never_asks_for_mask_and_source_is_validated(self):
        with mock.patch("satellite.client.call", return_value={}) as call:
            services.order(self.db, self.user, {"bbox": BBOX, "product": "ndvi", "mission": "s2_l1c", "scene": "S2B_AAAA_1",
                                                "mask": True, "source": "earthsearch"})
            self.assertFalse(call.call_args.args[2]["mask"])
            self.assertEqual(call.call_args.args[2]["source"], "earthsearch")
            with self.assertRaises(services.SatError) as e:
                services.order(self.db, self.user, {"bbox": BBOX, "product": "ndvi", "mission": "landsat", "scene": "LC09_XX_1",
                                                    "source": "earthsearch"})
            self.assertEqual(e.exception.code, "source")

    def test_search_refuses_layers_disabled_and_not_in_plan(self):
        for mission, plan_missions, code in (("dem", "", "mission"), ("landsat", "sentinel2", "mission")):
            self.plan.sat_missions = plan_missions
            self.plan.save()
            self.db.refresh_from_db()
            with self.assertRaises(services.SatError) as e:
                services.search(self.db, self.user, {"bbox": BBOX, "start": "2026-06-01", "end": "2026-06-30", "mission": mission})
            self.assertEqual(e.exception.code, code)


@GW
class MissionListTests(_Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def listing(self, live):
        with mock.patch("satellite.client.call", return_value={"missions": live}):
            return {m["key"]: m for m in self.client.get(reverse("satellite:missions", args=[self.db.pk])).json()["missions"]}

    def test_listing_has_groups_cost_and_provider_health(self):
        live = {k: {"ok": True, "ms": 5, "sources": {s.provider: {"ok": s.provider == "earthsearch"} for s in m.sources}}
                for k, m in spec.MISSIONS.items()}
        by = self.listing(live)
        self.assertEqual(set(by), set(spec.MISSIONS))
        self.assertEqual((by["s1_rtc"]["group"], by["s1_rtc"]["kind"], by["s1_rtc"]["cost"]), ("radar", "sar", 2))
        self.assertEqual(by["worldcover"]["kind"], "layer")
        self.assertFalse(by["s2_l1c"]["mask"])
        self.assertTrue(by["sentinel2"]["mask"])
        self.assertEqual([(p["key"], p["ok"]) for p in by["sentinel2"]["providers"]], [("earthsearch", True), ("planetary", False)])

    def test_panel_disabled_mission_disappears_and_plan_lock_is_flagged(self):
        self.set(m_water_enabled=False)
        self.plan.sat_missions = "sentinel2,dem"
        self.plan.save()
        by = self.listing({k: {"ok": True} for k in spec.MISSIONS})
        self.assertNotIn("water", by)
        self.assertTrue(by["dem"]["allowed"])
        self.assertFalse(by["landsat"]["allowed"])

    def test_old_gateway_offers_sentinel2_and_dem_only(self):
        with mock.patch("satellite.client.call", side_effect=client.GatewayError("پیدا نشد", 404)):
            by = {m["key"]: m for m in self.client.get(reverse("satellite:missions", args=[self.db.pk])).json()["missions"]}
        self.assertEqual({k for k, m in by.items() if m["available"]}, {"sentinel2", "dem"})

    def test_page_has_group_markers_and_conditional_fields(self):
        html = self.client.get(reverse("satellite:index", args=[self.db.pk])).content.decode()
        self.assertIn('data-when="scene"', html)
        self.assertIn('data-when="optical"', html)
        self.assertIn('"mission":"s1_rtc"', html.replace(" ", ""))
        self.assertIn('"mission":"worldcover"', html.replace(" ", ""))


@GW
class ProbePushTests(_Base):
    def test_probe_stops_when_config_cannot_be_pushed(self):
        health = mock.MagicMock()
        health.__enter__.return_value.read.return_value = b'{"ok": true, "version": "1.3", "configured": true}'
        with mock.patch("urllib.request.urlopen", return_value=health), \
                mock.patch("satellite.client.call", return_value={"ok": True}), \
                mock.patch("satellite.sources.push", return_value=(False, "دروازه نسخه‌ی قدیمی است")):
            steps = probe.run()
        self.assertEqual(steps[-1], (False, "دروازه نسخه‌ی قدیمی است"))


class AdminPageTests(_Base):
    def setUp(self):
        super().setUp()
        from core.models import SiteSettings
        SiteSettings.get()
        self.admin = User.objects.create_admin("boss", "Str0ng-Admin-Pass")
        self.client.force_login(self.admin)
        self.url = reverse("admin:core_sitesettings_satsources")
        p = mock.patch("satellite.sources.push", return_value=(True, "پیکربندی به دروازه رسید."))
        self.push = p.start()
        self.addCleanup(p.stop)

    def form(self, **over) -> dict:
        data = {}
        for m in spec.MISSIONS.values():
            data[f"m_{m.key}_enabled"] = "on"
            data[f"m_{m.key}_weight"] = str(m.weight)
            data[f"m_{m.key}_max_km2"] = "0"
            if len(m.sources) > 1:
                data[f"m_{m.key}_prefer"] = m.primary.provider
        for p in spec.PROVIDERS.values():
            data[f"prov_{p.key}_enabled"] = "on"
        data.update(over)
        return {k: v for k, v in data.items() if v is not None}

    def test_settings_tab_links_to_the_page_and_page_lists_everything(self):
        r = self.client.get(reverse("admin:core_sitesettings_change", args=[1]))
        self.assertContains(r, self.url)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        for m in spec.MISSIONS.values():
            self.assertContains(r, m.title)
        for p in spec.PROVIDERS.values():
            self.assertContains(r, p.title)
        self.assertContains(r, "eodata-s3keysmanager.dataspace.copernicus.eu")      # آدرس ثبت‌نام کلید
        self.assertContains(r, "cmr.earthdata.nasa.gov")                            # میزبان فایروال

    def test_save_applies_settings_and_pushes_to_gateway(self):
        r = self.client.post(self.url, self.form(m_landsat_enabled=None, m_s2_c1_weight="3", m_dem_prefer="planetary",
                                                 prov_planetary_url="https://pc.example.org/api", m_water_max_km2="40"), follow=True)
        self.assertContains(r, "پیکربندی به دروازه رسید")
        self.push.assert_called_once()
        v = conf.get_all(sources.PLUGIN)
        self.assertFalse(v["m_landsat_enabled"])
        self.assertTrue(v["m_sentinel2_enabled"])
        self.assertEqual((v["m_s2_c1_weight"], v["m_dem_prefer"], v["m_water_max_km2"]), (3, "planetary", 40))
        self.assertEqual(v["prov_planetary_url"], "https://pc.example.org/api")
        self.assertFalse(sources.mission_enabled("landsat"))

    def test_provider_card_says_key_needed_until_credentials_are_set(self):
        r = self.client.get(self.url)
        by = {p["key"]: p for p in r.context["providers"]}
        self.assertEqual((by["earthdata"]["status"], by["opentopography"]["status"]), ("کلید لازم", "کلید لازم"))
        self.assertEqual((by["earthsearch"]["status"], by["copernicus"]["status"]), ("روشن", "گام بعد"))
        self.client.post(self.url, self.form(prov_earthdata_user="me"), follow=True)               # نام کاربری بدون رمز: هنوز کافی نیست
        by = {p["key"]: p for p in self.client.get(self.url).context["providers"]}
        self.assertEqual(by["earthdata"]["status"], "کلید لازم")
        self.client.post(self.url, self.form(prov_earthdata_password="pw", prov_opentopography_api_key="K"), follow=True)
        by = {p["key"]: p for p in self.client.get(self.url).context["providers"]}
        self.assertEqual((by["earthdata"]["status"], by["opentopography"]["status"]), ("روشن", "روشن"))

    def test_bad_values_are_reported_and_not_pushed(self):
        r = self.client.post(self.url, self.form(m_landsat_weight="99", prov_earthsearch_url="http://insecure.example.org"), follow=True)
        self.assertContains(r, "https")
        self.assertContains(r, "m_landsat_weight")
        self.push.assert_not_called()

    def test_secrets_are_encrypted_hidden_and_clearable(self):
        self.client.post(self.url, self.form(prov_copernicus_s3_access="AKIA-ACCESS", prov_copernicus_s3_secret="TOP-SECRET-KEY"), follow=True)
        from kernel.models import PluginSetting
        raw = PluginSetting.objects.get(plugin_id=sources.PLUGIN, key="prov_copernicus_s3_secret").value
        self.assertNotIn("TOP-SECRET-KEY", raw)
        self.assertEqual(conf.get(sources.PLUGIN, "prov_copernicus_s3_secret"), "TOP-SECRET-KEY")
        page = self.client.get(self.url).content.decode()
        self.assertNotIn("TOP-SECRET-KEY", page)
        self.assertIn("تنظیم شده", page)
        # فرم بدون مقدار تازه، کلید را دست نمی‌زند
        self.client.post(self.url, self.form(), follow=True)
        self.assertEqual(conf.get(sources.PLUGIN, "prov_copernicus_s3_secret"), "TOP-SECRET-KEY")
        self.client.post(self.url, self.form(clear_copernicus_s3_secret="on"), follow=True)
        self.assertEqual(conf.get(sources.PLUGIN, "prov_copernicus_s3_secret"), "")

    def test_changing_a_secret_requires_fresh_confirmation(self):
        from kernel import stepup

        class Strict(stepup.Provider):
            def ok(self, request):
                return False

            def url(self, request):
                return "/confirm/"
        stepup.set_provider(Strict())
        self.addCleanup(stepup.set_provider, None)
        r = self.client.post(self.url, self.form(prov_earthdata_password="PW-123"))
        self.assertRedirects(r, "/confirm/", fetch_redirect_response=False)
        self.assertEqual(conf.get(sources.PLUGIN, "prov_earthdata_password"), "")
        self.assertEqual(self.client.post(self.url, self.form(m_landsat_weight="2")).status_code, 302)   # بدون راز: لازم نیست
        self.assertEqual(conf.get(sources.PLUGIN, "m_landsat_weight"), 2)

    def test_page_requires_staff(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
