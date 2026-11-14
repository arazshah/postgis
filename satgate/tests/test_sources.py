"""منابع تازه‌ی دروازه: رجیستری، پیکربندی زنده از پنل، جایگزینی تأمین‌کننده، لایه‌های آماده، رادار و ماهواره‌های بدون ماسک."""
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

from satgate import process, protocol, runtime, spec, stac
from satgate.app import Config, Gateway, make_app
from satgate.runtime import RUNTIME, ConfigError
from satgate.tests.test_gateway import BBOX, SECRET, make_scene

FULL = {"type": "Polygon", "coordinates": [[[51.0, 35.4], [51.7, 35.4], [51.7, 36.1], [51.0, 36.1], [51.0, 35.4]]]}


def cfg_doc(**over) -> dict:
    doc = {"v": 1, "providers": {}, "missions": {}}
    doc.update(over)
    return doc


class Base(unittest.TestCase):
    def setUp(self):
        RUNTIME.reset()
        stac._TOKENS.clear()
        self.addCleanup(RUNTIME.reset)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)


class RegistryTests(unittest.TestCase):
    def test_registry_is_consistent(self):
        for key, m in spec.MISSIONS.items():
            self.assertLessEqual(len(key), 12, key)                      # ستون mission در پایگاه داده ۱۲ نویسه است
            self.assertIn(m.kind, ("optical", "sar", "layer"))
            self.assertIn(m.group, dict(spec.GROUPS))
            self.assertTrue(m.attribution and m.license, key)           # ذکر منبع و مجوز برای هر لایه
            self.assertTrue(m.sources, key)
            for s in m.sources:
                self.assertTrue(spec.PROVIDERS[s.provider].implemented, key)
            prods = spec.PRODUCTS_BY_MISSION[key]
            self.assertTrue(prods, key)
            for pk, p in prods.items():
                self.assertLessEqual(len(pk), 20)
                self.assertEqual(p.mission, key)
                if m.kind == "layer":
                    self.assertFalse(p.needs_scene)
                    self.assertEqual(pk, key)
                    self.assertTrue(all(s.asset for s in m.sources), key)
                else:
                    for b in p.bands:
                        for s in m.sources:
                            self.assertIn(b, s.assets, f"{key}:{pk}:{b}")

    def test_old_gateway_contracts_still_hold(self):
        self.assertEqual(spec.get_product("anything", "dem").key, "dem")
        self.assertEqual(spec.MISSIONS["sentinel2"].collection, "sentinel-2-l2a")
        self.assertEqual(spec.MISSIONS["landsat"].platforms, ("landsat-8", "landsat-9"))
        self.assertEqual(spec.MISSIONS["landsat_old"].platforms, ("landsat-4", "landsat-5", "landsat-7"))
        self.assertTrue(spec.MISSIONS["sentinel2"].has_mask)
        self.assertFalse(spec.MISSIONS["s2_l1c"].has_mask)
        self.assertFalse(spec.MISSIONS["s1_rtc"].has_mask)

    def test_every_account_provider_declares_fields_and_signup(self):
        for p in spec.PROVIDERS.values():
            if p.account:
                self.assertTrue(p.creds and p.signup and p.hosts, p.key)
                self.assertFalse(p.implemented, p.key)


class RuntimeTests(Base):
    def test_defaults_without_panel_config(self):
        self.assertEqual(RUNTIME.hash, "")
        self.assertEqual([s.provider for s in RUNTIME.sources("sentinel2")], ["earthsearch", "planetary"])
        self.assertTrue(RUNTIME.mission_enabled("landsat"))
        self.assertFalse(RUNTIME.provider_enabled("copernicus"))              # حساب‌دار و هنوز بدون منبع
        self.assertEqual(RUNTIME.provider_url("planetary"), spec.PC_URL)

    def test_apply_sets_hash_urls_and_order(self):
        doc = cfg_doc(providers={"earthsearch": {"enabled": True, "url": "https://es.example.org/v1"}},
                      missions={"sentinel2": {"enabled": True, "prefer": "planetary"}, "landsat": {"enabled": False}})
        h = RUNTIME.apply(doc)
        self.assertEqual(h, protocol.config_hash(doc))
        self.assertEqual(RUNTIME.provider_url("earthsearch"), "https://es.example.org/v1")
        self.assertEqual([s.provider for s in RUNTIME.sources("sentinel2")], ["planetary", "earthsearch"])
        self.assertEqual(RUNTIME.sources("landsat"), [])

    def test_disabled_provider_is_skipped_and_hash_is_stable(self):
        RUNTIME.apply(cfg_doc(providers={"planetary": {"enabled": False}}))
        self.assertEqual([s.provider for s in RUNTIME.sources("sentinel2")], ["earthsearch"])
        self.assertEqual(RUNTIME.sources("landsat"), [])                     # فقط روی Planetary Computer است
        self.assertEqual(protocol.config_hash({"b": 1, "a": 2}), protocol.config_hash({"a": 2, "b": 1}))

    def test_credentials_are_stored_but_never_published(self):
        RUNTIME.apply(cfg_doc(providers={"copernicus": {"enabled": True, "cred": {"s3_access": "AK", "s3_secret": "SK"}}}))
        self.assertEqual(RUNTIME.cred("copernicus", "s3_secret"), "SK")
        pub = json.dumps(RUNTIME.public())
        self.assertNotIn("SK", pub)
        self.assertIn("s3_secret", pub)                                       # فقط نام فیلدِ تنظیم‌شده

    def test_validation_rejects_bad_documents(self):
        bad = [
            {"v": 2},
            cfg_doc(providers={"nope": {}}),
            cfg_doc(missions={"nope": {}}),
            cfg_doc(providers={"earthsearch": {"url": "http://es.example.org"}}),          # بدون https
            cfg_doc(providers={"earthsearch": {"url": "https://127.0.0.1/v1"}}),           # IP
            cfg_doc(providers={"earthsearch": {"url": "https://user:pw@es.example.org"}}),
            cfg_doc(providers={"earthsearch": {"url": "https://localhost/v1"}}),
            cfg_doc(providers={"copernicus": {"cred": {"unknown": "x"}}}),
            cfg_doc(providers={"copernicus": {"cred": {"s3_access": "x" * 700}}}),
            cfg_doc(missions={"landsat": {"prefer": "earthsearch"}}),                       # این ماهواره آن منبع را ندارد
            cfg_doc(missions={"landsat": {"max_km2": "abc"}}),
        ]
        for doc in bad:
            with self.assertRaises(ConfigError, msg=doc):
                runtime.validate(doc)
        self.assertEqual(RUNTIME.hash, "")


class SearchFailoverTests(Base):
    def feats(self, n=1, coll="sentinel-2-l2a"):
        return [{"id": f"S2A_39SUQ_2026060{i + 1}_0_L2A", "collection": coll, "geometry": FULL,
                 "properties": {"datetime": f"2026-06-0{i + 1}T07:00:00Z", "eo:cloud_cover": 3}} for i in range(n)]

    def test_falls_back_to_second_provider_and_marks_source(self):
        urls = []

        def fetch(url, body=None, timeout=30):
            urls.append(url)
            if "earth-search" in url:
                raise stac.StacError("به کاتالوگ تصویر وصل نشدیم.")
            return {"features": self.feats()}
        res = stac.search(BBOX, "2026-06-01", "2026-06-30", fetch=fetch)
        self.assertEqual([r["source"] for r in res], ["planetary"])
        self.assertIn("planetarycomputer", urls[-1])

    def test_primary_wins_when_it_answers_and_empty_primary_falls_through(self):
        def fetch(url, body=None, timeout=30):
            return {"features": self.feats() if "earth-search" in url else []}
        self.assertEqual(stac.search(BBOX, "2026-06-01", "2026-06-30", fetch=fetch)[0]["source"], "earthsearch")

        def only_second(url, body=None, timeout=30):
            return {"features": [] if "earth-search" in url else self.feats()}
        self.assertEqual(stac.search(BBOX, "2026-06-01", "2026-06-30", fetch=only_second)[0]["source"], "planetary")

    def test_all_down_raises_and_forced_source_is_respected(self):
        def down(url, body=None, timeout=30):
            raise stac.StacError("وصل نشدیم")
        with self.assertRaises(stac.StacError):
            stac.search(BBOX, "2026-06-01", "2026-06-30", fetch=down)
        seen = []

        def fetch(url, body=None, timeout=30):
            seen.append(url)
            return {"features": []}
        stac.search(BBOX, "2026-06-01", "2026-06-30", fetch=fetch, source="planetary")
        self.assertEqual(len(seen), 1)
        self.assertIn("planetarycomputer", seen[0])

    def test_disabled_mission_and_layers_are_not_searchable(self):
        RUNTIME.apply(cfg_doc(missions={"landsat": {"enabled": False}}))
        with self.assertRaises(stac.StacError):
            stac.search(BBOX, "2026-06-01", "2026-06-30", fetch=lambda *a, **k: {"features": []}, mission="landsat")
        with self.assertRaises(stac.StacError):
            stac.search(BBOX, "2026-06-01", "2026-06-30", fetch=lambda *a, **k: {"features": []}, mission="dem")

    def test_query_per_kind_and_platform(self):
        seen = {}

        def fake(url, body=None, timeout=30):
            seen.update(body=body)
            return {"features": []}
        stac.search(BBOX, "2026-06-01", "2026-06-30", 20, fetch=fake, mission="landsat_old")
        self.assertEqual(seen["body"]["query"]["platform"], {"in": ["landsat-4", "landsat-5", "landsat-7"]})
        stac.search(BBOX, "2026-06-01", "2026-06-30", 20, fetch=fake, mission="s1_rtc")
        self.assertNotIn("query", seen["body"])                                # رادار ابر ندارد
        stac.search(BBOX, "2026-06-01", "2026-06-30", 20, fetch=fake, mission="s2_c1")
        self.assertEqual(seen["body"]["collections"], ["sentinel-2-c1-l2a"])

    def test_layer_items_fail_over_and_use_fixed_datetime(self):
        bodies = []

        def fetch(url, body=None, timeout=30):
            bodies.append((url, body))
            if "earth-search" in url:
                raise stac.StacError("وصل نشدیم")
            return {"features": [{"id": "tile", "assets": {"data": {"href": "x"}}}]}
        src, items = stac.layer_items(spec.MISSIONS["dem90"], BBOX, fetch)
        self.assertEqual((src.provider, len(items)), ("planetary", 1))
        self.assertEqual(bodies[-1][1]["collections"], ["cop-dem-glo-90"])
        stac.layer_items(spec.MISSIONS["worldcover"], BBOX, fetch)
        self.assertEqual(bodies[-1][1]["datetime"], "2021-01-01T00:00:00Z/2021-12-31T23:59:59Z")


class SigningAndCheckTests(Base):
    def test_sentinel2_on_azure_is_signed_but_on_aws_is_not(self):
        calls = []

        def fake(url, body=None, timeout=30):
            calls.append(url)
            return {"token": "sig=q", "msft:expiry": "2099-01-01T00:00:00Z"}
        az = "https://sentinel2l2a01.blob.core.windows.net/s2/x/B04.tif"
        self.assertEqual(stac.sign_href("sentinel-2-l2a", az, fake), az + "?sig=q")
        self.assertIn("/token/sentinel-2-l2a", calls[0])
        aws = "https://sentinel-cogs.s3.us-west-2.amazonaws.com/x.tif"
        self.assertEqual(stac.sign_href("sentinel-2-l2a", aws, fake), aws)
        self.assertEqual(stac.sign_href("cop-dem-glo-30", az, fake), az + "?sig=q")      # این مجموعه هم روی Planetary هست
        self.assertEqual(stac.sign_href("not-hosted-anywhere", az, fake), az)

    def feature(self, m: spec.Mission, src: spec.Source, drop=()) -> dict:
        names = [src.asset] if m.kind == "layer" else list(src.assets.values())
        if src.mask_asset:
            names.append(src.mask_asset)
        return {"id": "X", "assets": {n: {"href": "https://x.example/" + n} for n in names if n not in drop}}

    def test_strict_check_catches_wrong_asset_names(self):
        m = spec.MISSIONS["s2_c1"]
        src = m.primary
        ok = stac.check_mission("s2_c1", fetch=lambda *a, **k: {"features": [self.feature(m, src)]}, open_url=lambda h: b"x", strict=True)
        self.assertTrue(ok["ok"], ok)
        bad = stac.check_mission("s2_c1", fetch=lambda *a, **k: {"features": [self.feature(m, src, drop=("nir",))]},
                                 open_url=lambda h: b"x", strict=True)
        self.assertFalse(bad["ok"])
        self.assertIn("nir", bad["error"])
        empty = stac.check_mission("s2_c1", fetch=lambda *a, **k: {"features": []}, strict=True)
        self.assertFalse(empty["ok"])
        self.assertTrue(stac.check_mission("s2_c1", fetch=lambda *a, **k: {"features": []})["ok"])      # غیرسخت‌گیرانه مثل قبل

    def test_mission_ok_if_any_source_works_and_reports_each(self):
        m = spec.MISSIONS["dem"]

        def fetch(url, body=None, timeout=30):
            if "earth-search" in url:
                raise stac.StacError("وصل نشدیم")
            return {"features": [self.feature(m, m.sources[1])]}
        r = stac.check_mission("dem", fetch=fetch, open_url=lambda h: b"x", strict=True)
        self.assertTrue(r["ok"])
        self.assertEqual({k: v["ok"] for k, v in r["sources"].items()}, {"earthsearch": False, "planetary": True})

    def test_disabled_mission_is_reported_not_probed(self):
        RUNTIME.apply(cfg_doc(missions={"water": {"enabled": False}}))
        called = []
        r = stac.check_mission("water", fetch=lambda *a, **k: called.append(1) or {"features": []})
        self.assertEqual((r["ok"], r.get("disabled"), called), (False, True, []))


# ---------------------------------------------------------------- داده‌ی ساختگی
def tile(path: Path, west: float, south: float, deg: float, value, dtype="uint8", nodata=None, res=0.001) -> str:
    n = int(round(deg / res))
    with rasterio.open(path, "w", driver="GTiff", width=n, height=n, count=1, dtype=dtype, crs="EPSG:4326",
                       transform=from_origin(west, south + deg, res, res), nodata=nodata) as dst:
        dst.write(np.full((n, n), value, dtype=dtype), 1)
    return str(path)


def sar_item(root: Path, vv=0.1, vh=0.02, tag="", hole=False) -> dict:
    """صحنه‌ی ساختگی Sentinel-1 RTC: توان خطی float32 روی UTM 39N با بی‌داده‌ی -32768."""
    w, s, e, n = transform_bounds("EPSG:4326", "EPSG:32639", 51.2, 35.6, 51.45, 35.85)
    ox, oy = int(w // 10 * 10), int(n // 10 * 10)
    size = int((e - w) / 10) + 2, int((n - s) / 10) + 2
    assets = {}
    for name, v in (("vv", vv), ("vh", vh)):
        arr = np.full((size[1], size[0]), v, dtype="float32")
        if hole:
            arr[: size[1] // 2, :] = -32768
        path = root / f"{tag}{name}.tif"
        with rasterio.open(path, "w", driver="GTiff", width=size[0], height=size[1], count=1, dtype="float32", crs="EPSG:32639",
                           transform=from_origin(ox, oy, 10, 10), nodata=-32768) as dst:
            dst.write(arr, 1)
        assets[name] = {"href": str(path)}
    return {"id": f"S1A_IW_{tag}", "collection": "sentinel-1-rtc", "assets": assets, "properties": {"datetime": "2026-06-01T03:00:00Z"}}


class LayerTests(Base):
    def test_mosaic_of_two_tiles_keeps_uint8_and_nodata(self):
        a = tile(self.root / "a.tif", 51.25, 35.65, 0.1, 10, nodata=0)
        b = tile(self.root / "b.tif", 51.35, 35.65, 0.1, 20, nodata=0)
        items = [{"id": "a", "assets": {"map": {"href": a}}}, {"id": "b", "assets": {"map": {"href": b}}}]
        box = [51.30, 35.70, 51.40, 35.73]
        out = process.build_layer(items, "worldcover", box, self.root / "w.tif")
        with rasterio.open(out) as ds:
            self.assertEqual((ds.dtypes[0], ds.nodata, ds.count), ("uint8", 0, 1))
            data = ds.read(1)
            self.assertEqual(set(np.unique(data)), {10, 20})
            self.assertEqual(ds.descriptions[0], "worldcover")

    def test_dem_variants_are_float32_with_minus_9999(self):
        t = tile(self.root / "d.tif", 51.2, 35.6, 0.3, 1500, dtype="int16", nodata=-32768)
        for mission, asset in (("dem90", "data"), ("nasadem", "elevation"), ("alosdem", "data"), ("dem", "data")):
            out = process.build_layer([{"id": "t", "assets": {asset: {"href": t}}}], mission, BBOX, self.root / f"{mission}.tif")
            with rasterio.open(out) as ds:
                self.assertEqual((ds.dtypes[0], ds.nodata), ("float32", -9999.0), mission)
                self.assertAlmostEqual(float(ds.read(1).mean()), 1500, places=1)

    def test_missing_data_is_a_clear_error(self):
        with self.assertRaises(process.ProcessError):
            process.build_layer([], "water", BBOX, self.root / "x.tif")
        with self.assertRaises(process.ProcessError):
            process.build_layer([{"assets": {"other": {"href": "x"}}}], "water", BBOX, self.root / "x.tif")

    def test_old_build_dem_wrapper(self):
        t = tile(self.root / "d.tif", 51.2, 35.6, 0.3, 900, dtype="int16", nodata=-32768)
        out = process.build_dem([{"assets": {"data": {"href": t}}}], BBOX, self.root / "old.tif")
        with rasterio.open(out) as ds:
            self.assertEqual(ds.dtypes[0], "float32")


class SarTests(Base):
    def test_vv_in_decibels(self):
        item = sar_item(self.root, vv=0.1, vh=0.01)
        out, used = process.build_sar([item], "s1_rtc", "vv_db", BBOX, self.root / "vv.tif")
        self.assertEqual(used, 1)
        with rasterio.open(out) as ds:
            self.assertEqual((ds.dtypes[0], ds.nodata, ds.res[0]), ("float32", -9999.0, 10.0))
            self.assertAlmostEqual(float(np.median(ds.read(1))), -10.0, places=1)
        out, _ = process.build_sar([item], "s1_rtc", "vh_db", BBOX, self.root / "vh.tif")
        with rasterio.open(out) as ds:
            self.assertAlmostEqual(float(np.median(ds.read(1))), -20.0, places=1)

    def test_false_color_is_rgb_byte(self):
        out, _ = process.build_sar([sar_item(self.root, 0.1, 0.01)], "s1_rtc", "sar_rgb", BBOX, self.root / "rgb.tif")
        with rasterio.open(out) as ds:
            self.assertEqual((ds.count, ds.dtypes[0], ds.nodata), (3, "uint8", 0.0))
            r, g, b = (ds.read(i) for i in (1, 2, 3))
            self.assertGreater(int(np.median(r)), int(np.median(g)))        # VV (−10 dB) روشن‌تر از VH (−20 dB)
            self.assertTrue((b[b > 0] <= 255).all())

    def test_median_of_scenes_ignores_invalid_pixels(self):
        a = sar_item(self.root, vv=0.1, tag="a_")
        b = sar_item(self.root, vv=0.4, tag="b_", hole=True)               # نیمه‌ی شمالی بی‌داده
        out, used = process.build_sar([a, b], "s1_rtc", "vv_db", BBOX, self.root / "m.tif")
        self.assertEqual(used, 2)
        with rasterio.open(out) as ds:
            data = ds.read(1)
            valid = data[data != -9999]
            self.assertGreater(valid.size, 0)
            self.assertTrue(set(np.round(np.unique(valid))) <= {-10.0, -7.0, -8.0, -9.0, -6.0, -5.0, -4.0})

    def test_scene_without_polarization_is_skipped_or_errors(self):
        item = sar_item(self.root)
        del item["assets"]["vh"]
        with self.assertRaises(process.ProcessError):
            process.build_sar([item], "s1_rtc", "vh_db", BBOX, self.root / "x.tif")
        self.assertEqual(process.build_sar([item], "s1_rtc", "vv_db", BBOX, self.root / "y.tif")[1], 1)


class OpticalVariantTests(Base):
    def test_l1c_has_no_mask_but_builds_without_it(self):
        item = make_scene(self.root, nir_v=4000, red_v=2000)           # بازتاب ۰٫۳ و ۰٫۱ ← NDVI = ۰٫۵
        item["collection"] = "sentinel-2-l1c"
        item["assets"].pop("scl")
        with self.assertRaises(process.ProcessError) as e:
            process.build_scene(item, "s2_l1c", "ndvi", BBOX, self.root / "a.tif", mask=True)
        self.assertIn("ماسک", str(e.exception))
        out = process.build_scene(item, "s2_l1c", "ndvi", BBOX, self.root / "b.tif", mask=False)
        with rasterio.open(out) as ds:
            self.assertAlmostEqual(float(ds.read(1).mean()), 0.5, places=2)

    def test_collection_one_uses_scl_mask(self):
        item = make_scene(self.root, cloud="all")
        out = process.build_scene(item, "s2_c1", "ndvi", BBOX, self.root / "c.tif", mask=True)
        with rasterio.open(out) as ds:
            self.assertTrue((ds.read(1) == -9999).all())

    def test_planetary_fallback_uses_its_own_band_names(self):
        item = make_scene(self.root, nir_v=4000, red_v=2000)
        pc = spec.MISSIONS["sentinel2"].source("planetary")
        renamed = {"B04": "red", "B03": "green", "B02": "blue", "B08": "nir", "B05": "rededge1", "B06": "rededge2",
                   "B07": "rededge3", "B8A": "nir08", "B11": "swir16", "B12": "swir22", "SCL": "scl"}
        item["assets"] = {new: item["assets"][old] for new, old in renamed.items()}
        out = process.build_scene(item, "sentinel2", "ndvi", BBOX, self.root / "pc.tif", mask=True, source=pc)
        with rasterio.open(out) as ds:
            self.assertAlmostEqual(float(ds.read(1).mean()), 0.5, places=2)
        with self.assertRaises(process.ProcessError):                       # با نام‌های Earth Search همین تصویر ناقص است
            process.build_scene(item, "sentinel2", "ndvi", BBOX, self.root / "x.tif")

    def test_old_landsat_uses_landsat_scaling(self):
        from satgate.tests.test_gateway import make_landsat
        item = make_landsat(self.root)
        item["properties"]["platform"] = "landsat-5"
        out = process.build_scene(item, "landsat_old", "ndvi", BBOX, self.root / "l5.tif")
        with rasterio.open(out) as ds:
            nir, red = 20000 * 2.75e-5 - 0.2, 15000 * 2.75e-5 - 0.2
            self.assertAlmostEqual(float(ds.read(1).mean()), (nir - red) / (nir + red), places=3)


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.scene = make_scene(self.root)
        self.fetched = []

        def fetch(url, body=None, timeout=30):
            self.fetched.append((url, body))
            if "/items/" in url:
                return self.scene
            return {"features": []}
        cfg = Config({"SATGATE_SECRET": SECRET, "SATGATE_PANEL_URL": "https://panel.test", "SATGATE_DATA": str(self.root / "d"),
                      "SATGATE_MAX_KM2": "200", "SATGATE_WORKERS": "1"})
        self.gw = Gateway(cfg, fetch=fetch, post=lambda path, body: None)
        self.gw.notify = lambda job: None
        self.app = make_app(self.gw)
        self.addCleanup(self.gw.pool.shutdown, True)

    def call(self, method, path, body=None):
        raw = json.dumps(body).encode() if body is not None else b""
        h = protocol.sign(SECRET, method, path, raw)
        env = {"REQUEST_METHOD": method, "PATH_INFO": path.split("?")[0], "QUERY_STRING": path.partition("?")[2],
               "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw),
               "HTTP_X_SAT_TIME": h[protocol.H_TIME], "HTTP_X_SAT_SIG": h[protocol.H_SIG]}
        out = {}
        data = b"".join(self.app(env, lambda status, hdr: out.update(status=int(status.split()[0]))))
        out["json"] = json.loads(data) if data[:1] in (b"{", b"[") else None
        return out

    def wait(self, jid):
        for _ in range(100):
            j = self.call("GET", f"/v1/jobs/{jid}")["json"]
            if j["status"] in ("ready", "failed"):
                return j
            time.sleep(0.1)
        self.fail("timeout")

    def test_config_put_get_and_health_hash(self):
        doc = cfg_doc(providers={"copernicus": {"enabled": True, "cred": {"s3_secret": "TOPSECRET"}}})
        r = self.call("PUT", "/v1/config", doc)
        self.assertEqual((r["status"], r["json"]["hash"]), (200, protocol.config_hash(doc)))
        got = self.call("GET", "/v1/config")["json"]
        self.assertEqual(got["hash"], protocol.config_hash(doc))
        self.assertNotIn("TOPSECRET", json.dumps(got))
        health = self.call("GET", "/v1/health")["json"]
        self.assertEqual(health["cfg"], protocol.config_hash(doc))
        self.assertEqual(self.call("PUT", "/v1/config", {"v": 1, "providers": {"x": {}}})["status"], 422)
        self.assertEqual(RUNTIME.hash, protocol.config_hash(doc))              # پیکربندی نامعتبر قبلی را خراب نکرد

    def test_unsigned_config_is_rejected(self):
        env = {"REQUEST_METHOD": "PUT", "PATH_INFO": "/v1/config", "QUERY_STRING": "", "CONTENT_LENGTH": "2", "wsgi.input": io.BytesIO(b"{}")}
        out = {}
        self.app(env, lambda status, hdr: out.update(status=int(status.split()[0])))
        self.assertEqual(out["status"], 401)

    def test_stale_config_hash_gets_409_until_panel_sends_it(self):
        job = {"id": "a" * 32, "product": "ndvi", "scene": "S2A_39SUQ_20260601_0_L2A", "bbox": BBOX, "cfg": "deadbeef"}
        r = self.call("POST", "/v1/jobs", job)
        self.assertEqual((r["status"], r["json"]["reason"]), (409, "config"))
        self.assertEqual(self.call("POST", "/v1/search", {"bbox": BBOX, "start": "2026-06-01", "end": "2026-06-30", "cfg": "deadbeef"})["status"], 409)
        self.assertEqual(self.call("POST", "/v1/analyze", {"cfg": "deadbeef"})["status"], 409)
        h = self.call("PUT", "/v1/config", cfg_doc())["json"]["hash"]
        self.assertEqual(self.call("POST", "/v1/jobs", {**job, "cfg": h})["status"], 202)
        legacy = {k: v for k, v in job.items() if k != "cfg"}
        self.assertEqual(self.call("POST", "/v1/jobs", {**legacy, "id": "b" * 32})["status"], 202)    # بدون cfg (پنل قدیمی) هم کار می‌کند

    def test_disabled_mission_and_bad_source_are_rejected(self):
        self.call("PUT", "/v1/config", cfg_doc(missions={"landsat": {"enabled": False}}))
        r = self.call("POST", "/v1/jobs", {"id": "c" * 32, "product": "ndvi", "mission": "landsat", "scene": "x", "bbox": BBOX})
        self.assertEqual(r["status"], 422)
        r = self.call("POST", "/v1/jobs", {"id": "d" * 32, "product": "ndvi", "scene": "x", "bbox": BBOX, "source": "copernicus"})
        self.assertEqual(r["status"], 400)

    def test_mission_cap_from_panel_lowers_area_limit(self):
        big = [51.2, 35.6, 51.3, 35.7]                                          # حدود ۹۰ کیلومتر مربع
        job = {"id": "e" * 32, "product": "ndvi", "scene": "S2A_39SUQ_20260601_0_L2A", "bbox": big}
        self.assertEqual(self.call("POST", "/v1/jobs", job)["status"], 202)
        self.wait("e" * 32)
        self.call("PUT", "/v1/config", cfg_doc(missions={"sentinel2": {"max_km2": 20}}))
        r = self.call("POST", "/v1/jobs", {**job, "id": "f" * 32})
        self.assertEqual(r["status"], 422)
        self.assertIn("سقف", r["json"]["error"])

    def test_layer_job_end_to_end_with_failover(self):
        t = tile(self.root / "w.tif", 51.2, 35.6, 0.3, 30, nodata=0)

        def fetch(url, body=None, timeout=30):
            if "earth-search" in url:
                raise stac.StacError("وصل نشدیم")
            return {"features": [{"id": "tile", "assets": {"map": {"href": t}}}]}
        self.gw.fetch = fetch
        r = self.call("POST", "/v1/jobs", {"id": "1" * 32, "product": "worldcover", "mission": "worldcover", "bbox": BBOX})
        self.assertEqual(r["status"], 202, r)
        job = self.wait("1" * 32)
        self.assertEqual(job["status"], "ready", job)
        with rasterio.open(self.gw.store.file("1" * 32)) as ds:
            self.assertEqual((ds.dtypes[0], int(ds.read(1).max())), ("uint8", 30))

    def test_sar_scene_and_composite_jobs(self):
        item = sar_item(self.root, vv=0.1, vh=0.02, tag="j_")
        item["id"] = "S1A_IW_ONE"

        def fetch(url, body=None, timeout=30):
            if "/items/" in url:
                return item
            return {"features": [{"id": "S1A_IW_ONE", "collection": "sentinel-1-rtc", "geometry": FULL,
                                  "properties": {"datetime": "2026-06-01T03:00:00Z"}}]}
        self.gw.fetch = fetch
        r = self.call("POST", "/v1/jobs", {"id": "2" * 32, "product": "vv_db", "mission": "s1_rtc", "scene": "S1A_IW_ONE", "bbox": BBOX})
        self.assertEqual(r["status"], 202, r)
        self.assertEqual(self.wait("2" * 32)["status"], "ready")
        comp = {"start": "2026-05-01", "end": "2026-06-30", "max_cloud": 100, "max_scenes": 3}
        r = self.call("POST", "/v1/jobs", {"id": "3" * 32, "product": "sar_rgb", "mission": "s1_rtc", "composite": comp, "bbox": BBOX})
        self.assertEqual(r["status"], 202, r)
        job = self.wait("3" * 32)
        self.assertEqual((job["status"], job.get("used")), ("ready", 1), job)
        # رادار بدون صحنه و بدون ترکیب پذیرفته نمی‌شود
        self.assertEqual(self.call("POST", "/v1/jobs", {"id": "4" * 32, "product": "vv_db", "mission": "s1_rtc", "bbox": BBOX})["status"], 400)

    def test_zonal_analysis_refuses_radar_and_layers(self):
        from satgate import analysis
        body = {"mission": "s1_rtc", "index": "ndvi", "features": [{"id": "1", "geometry": {"type": "Polygon", "coordinates": [[[51.3, 35.7], [51.31, 35.7], [51.31, 35.71], [51.3, 35.7]]]}}],
                "start": "2026-06-01", "end": "2026-06-30"}
        p, err = analysis.validate(body, 100)
        self.assertIsNone(p)
        self.assertIn("چندطیفی", err)
        p, err = analysis.validate({**body, "mission": "s2_l1c"}, 100)
        self.assertEqual(err, "")
        self.assertFalse(p["mask"])                                             # L1C ماسک ندارد؛ بی‌صدا خاموش می‌شود

    def test_missions_endpoint_lists_every_mission_with_sources(self):
        names = {a for m in spec.MISSIONS.values() for s_ in m.sources for a in (*s_.assets.values(), s_.mask_asset, s_.asset) if a}
        feat = {"id": "X", "assets": {a: {"href": "https://x.example/" + a} for a in names}}
        self.gw.fetch = lambda url, body=None, timeout=30: {"features": [feat]}
        with mock.patch.object(stac, "_read_head", lambda href: b"x"):
            res = self.call("GET", "/v1/missions?refresh=1")["json"]["missions"]
        self.assertEqual(set(res), set(spec.MISSIONS))
        self.assertTrue(all(v["ok"] for v in res.values()), {k: v for k, v in res.items() if not v["ok"]})
        self.assertEqual(set(res["sentinel2"]["sources"]), {"earthsearch", "planetary"})


if __name__ == "__main__":
    unittest.main()
