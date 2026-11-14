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

from satgate import auth, otapi, process, protocol, runtime, spec, stac
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
                    self.assertTrue(all(s.asset or s.api for s in m.sources), key)
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
                self.assertTrue(p.implemented, p.key)

    def test_jaxa_card_is_gone_and_palsar_comes_from_planetary(self):
        self.assertNotIn("jaxa", spec.PROVIDERS)
        for k in ("palsar_hh", "palsar_hv"):
            m = spec.MISSIONS[k]
            self.assertEqual((m.kind, m.group, m.sources[0].provider, m.sources[0].collection), ("layer", "radar", "planetary", "alos-palsar-mosaic"))
            p = spec.get_product(k, k)
            self.assertEqual((p.convert, p.src_dtype, p.dtype, p.nodata), ("palsar_db", "uint16", "float32", -9999))

    def test_provider_readiness_rules(self):
        ed, ot = spec.PROVIDERS["earthdata"], spec.PROVIDERS["opentopography"]
        self.assertTrue(ed.ready({"token": "t"}))
        self.assertTrue(ed.ready({"user": "u", "password": "p"}))
        self.assertFalse(ed.ready({"user": "u"}))                          # نام کاربری بدون رمز کافی نیست
        self.assertFalse(ed.ready({}))
        self.assertTrue(ot.ready({"api_key": "k"}))
        self.assertFalse(ot.ready(None))
        self.assertTrue(spec.PROVIDERS["earthsearch"].ready(None))


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
            cfg_doc(providers={"copernicus": {"cred": {"s3_access": "x" * 5000}}}),
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

    def test_probe_reads_s3_hrefs_over_https(self):
        seen = []

        class R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                return b"II*\x00"
        with mock.patch("urllib.request.urlopen", side_effect=lambda req, timeout=0: (seen.append(req.full_url), R())[1]):
            self.assertTrue(stac._read_head("s3://copernicus-dem-30m/Copernicus_DSM/x/y.tif"))
            stac._read_head("https://a.example/x.tif")
        self.assertEqual(seen, ["https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM/x/y.tif", "https://a.example/x.tif"])
        self.assertEqual(spec.https_href("/local/x.tif"), "/local/x.tif")

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
        r = self.call("POST", "/v1/jobs", {"id": "d" * 32, "product": "ndvi", "scene": "x", "bbox": BBOX, "source": "opentopography"})
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
        self.call("PUT", "/v1/config", cfg_doc(providers={"earthdata": {"enabled": True, "cred": {"token": "T"}},
                                                          "opentopography": {"enabled": True, "cred": {"api_key": "K"}}}))
        names = {a for m in spec.MISSIONS.values() for s_ in m.sources for a in (*s_.assets.values(), s_.mask_asset, s_.asset) if a}
        feat = {"id": "X", "assets": {a: {"href": "https://x.example/" + a} for a in names}}
        self.gw.fetch = lambda url, body=None, timeout=30: {"features": [feat]}
        with mock.patch.object(stac, "_read_head", lambda href: b"x"), mock.patch.object(otapi, "probe", lambda *a, **k: 1000):
            res = self.call("GET", "/v1/missions?refresh=1")["json"]["missions"]
        self.assertEqual(set(res), set(spec.MISSIONS))
        self.assertTrue(all(v["ok"] for v in res.values()), {k: v for k, v in res.items() if not v["ok"]})
        self.assertEqual(set(res["sentinel2"]["sources"]), {"earthsearch", "planetary"})
        self.assertEqual(set(res["dem"]["sources"]), {"earthsearch", "planetary", "opentopography"})


class AccountMissionTests(Base):
    """ماهواره‌ی حساب‌دار تا اعتبارنامه نرسد پنهان است؛ با رسیدنش فعال می‌شود."""

    def test_missions_need_credentials(self):
        self.assertEqual(RUNTIME.sources("hls_s30"), [])
        self.assertEqual(RUNTIME.sources("srtm30"), [])
        self.assertEqual([s.provider for s in RUNTIME.sources("dem")], ["earthsearch", "planetary"])      # OT فقط با کلید
        RUNTIME.apply(cfg_doc(providers={"earthdata": {"enabled": True, "cred": {"user": "u"}}}))
        self.assertEqual(RUNTIME.sources("hls_s30"), [])                                                   # رمز ندارد
        RUNTIME.apply(cfg_doc(providers={"earthdata": {"enabled": True, "cred": {"token": "T"}},
                                         "opentopography": {"enabled": True, "cred": {"api_key": "K"}}}))
        self.assertEqual([s.provider for s in RUNTIME.sources("hls_s30")], ["earthdata"])
        self.assertEqual([s.provider for s in RUNTIME.sources("dem")], ["earthsearch", "planetary", "opentopography"])
        RUNTIME.apply(cfg_doc(providers={"opentopography": {"enabled": True, "cred": {"api_key": "K"}}}, missions={"dem": {"prefer": "opentopography"}}))
        self.assertEqual(RUNTIME.sources("dem")[0].provider, "opentopography")

    def test_long_jwt_token_is_accepted_with_specific_errors_otherwise(self):
        jwt = "eyJ0eXAiOiJKV1QiLCJvcmlnaW4iOiJFYXJ0aGRhdGEgTG9naW4i" + "A" * 1400            # توکن واقعی Earthdata بیش از هزار نویسه است
        doc = cfg_doc(providers={"earthdata": {"enabled": True, "cred": {"token": jwt}}})
        self.assertEqual(RUNTIME.apply(doc), protocol.config_hash(doc))
        self.assertEqual(RUNTIME.cred("earthdata", "token"), jwt)
        with self.assertRaises(ConfigError) as e:
            runtime.validate(cfg_doc(providers={"earthdata": {"cred": {"token": "x" * 5000}}}))
        self.assertIn("«token»", str(e.exception))
        with self.assertRaises(ConfigError) as e:
            runtime.validate(cfg_doc(providers={"earthdata": {"cred": {"nope": "x"}}}))
        self.assertIn("nope", str(e.exception))

    def test_hls_search_uses_cmr_stac_and_cloud_filter(self):
        RUNTIME.apply(cfg_doc(providers={"earthdata": {"enabled": True, "cred": {"token": "T"}}}))
        seen = {}

        def fake(url, body=None, timeout=30):
            seen.update(url=url, body=body)
            return {"features": [{"id": "HLS.S30.T39SUQ.2026152T071229.v2.0", "collection": "HLSS30.v2.0", "geometry": FULL,
                                  "properties": {"datetime": "2026-06-01T07:12:29Z", "eo:cloud_cover": 7}}]}
        res = stac.search(BBOX, "2026-06-01", "2026-06-30", 20, fetch=fake, mission="hls_s30")
        self.assertEqual(seen["url"], "https://cmr.earthdata.nasa.gov/stac/LPCLOUD/search")
        self.assertEqual(seen["body"]["collections"], ["HLSS30.v2.0"])
        self.assertEqual(seen["body"]["query"], {"eo:cloud_cover": {"lte": 20.0}})
        self.assertEqual((res[0]["source"], res[0]["satellite"]), ("earthdata", "HLS Sentinel-2"))

    def test_hls_mask_bits(self):
        mask = np.array([[0, 2, 4, 8, 16, 32, 255, 64]], dtype="uint8")        # پاک، ابر، مجاور، سایه، برف، آب، بی‌داده، آئروسل
        bad = process.bad_pixels("hls_s30", mask)
        self.assertEqual(bad.tolist(), [[False, True, True, True, False, False, True, False]])

    def make_hls(self, nir=3000, red=1000, fmask=None):
        w, s, e, n = transform_bounds("EPSG:4326", "EPSG:32639", 51.1, 35.5, 51.55, 35.95)
        ox, oy = int(w // 30 * 30), int(n // 30 * 30)
        size = int((e - w) / 30) + 2, int((n - s) / 30) + 2
        assets = {}
        for name, v in {"B04": red, "B03": 1200, "B02": 900, "B8A": nir, "B11": 2000, "B12": 1600}.items():
            arr = np.full((size[1], size[0]), v, dtype="int16")
            arr[0, 0] = -9999
            path = self.root / f"hls_{name}.tif"
            with rasterio.open(path, "w", driver="GTiff", width=size[0], height=size[1], count=1, dtype="int16", crs="EPSG:32639",
                               transform=from_origin(ox, oy, 30, 30), nodata=-9999) as dst:
                dst.write(arr, 1)
            assets[name] = {"href": str(path)}
        fm = np.zeros((size[1], size[0]), dtype="uint8") if fmask is None else fmask(size)
        fpath = self.root / "hls_Fmask.tif"
        with rasterio.open(fpath, "w", driver="GTiff", width=size[0], height=size[1], count=1, dtype="uint8", crs="EPSG:32639",
                           transform=from_origin(ox, oy, 30, 30), nodata=255) as dst:
            dst.write(fm, 1)
        assets["Fmask"] = {"href": str(fpath)}
        return {"id": "HLS.S30.T39SUQ.2026152T071229.v2.0", "collection": "HLSS30.v2.0", "assets": assets,
                "properties": {"datetime": "2026-06-01T07:12:29Z", "eo:cloud_cover": 3}}

    def test_hls_ndvi_scale_and_mask(self):
        item = self.make_hls(nir=4000, red=2000)
        out = process.build_scene(item, "hls_s30", "ndvi", BBOX, self.root / "h.tif", mask=True)
        with rasterio.open(out) as ds:
            self.assertAlmostEqual(float(ds.read(1).mean()), (0.4 - 0.2) / (0.4 + 0.2), places=2)       # مقیاس ۰٫۰۰۰۱ و بدون جابه‌جایی
            self.assertAlmostEqual(ds.res[0], 30, places=3)
        cloudy = self.make_hls(fmask=lambda size: np.full((size[1], size[0]), 2, dtype="uint8"))
        out = process.build_scene(cloudy, "hls_s30", "ndvi", BBOX, self.root / "c.tif", mask=True)
        with rasterio.open(out) as ds:
            self.assertTrue((ds.read(1) == -9999).all())

    def test_hls_composite_on_common_grid(self):
        item = self.make_hls(nir=4000, red=2000)
        out, used = process.build_composite([item], "hls_s30", "ndvi", BBOX, self.root / "hc.tif")
        self.assertEqual(used, 1)
        with rasterio.open(out) as ds:
            self.assertAlmostEqual(float(np.median(ds.read(1))), 1 / 3, places=2)

    def test_nodata_edge_is_not_blended_into_values(self):
        """بی‌داده‌ی -9999 باید به بی‌داده‌ی خروجی بروند و با بازنمونه‌گیری مقدار کاذب نسازند."""
        item = self.make_hls(nir=4000, red=2000)
        grid = process.utm_grid(BBOX, 30)
        r = process.scene_refl(item, "hls_s30", ("red",), grid, mask=False)["red"]
        valid = r[np.isfinite(r)]
        self.assertTrue(np.allclose(valid, 0.2, atol=1e-4))

    def test_earthdata_token_resolve_and_redirect(self):
        import io
        import urllib.error
        auth.reset()
        self.addCleanup(auth.reset)
        RUNTIME.apply(cfg_doc(providers={"earthdata": {"enabled": True, "cred": {"token": "TOK"}}}))
        seen = []

        def opener(req, timeout=20):
            seen.append((req.full_url, req.get_header("Authorization"), req.get_header("Range")))
            raise urllib.error.HTTPError(req.full_url, 302, "Found", {"Location": "https://s3.example/presigned?sig=1"}, io.BytesIO())
        href = "https://data.lpdaac.earthdatacloud.nasa.gov/lp-protected/HLSS30.020/x/x.B04.tif"
        self.assertEqual(auth.resolve_edl(href, opener), "https://s3.example/presigned?sig=1")
        self.assertEqual(auth.resolve_edl(href, opener), "https://s3.example/presigned?sig=1")        # کش
        self.assertEqual(seen, [(href, "Bearer TOK", "bytes=0-0")])
        with mock.patch.object(auth, "_open_noredirect", opener):
            auth._urls.clear()
            self.assertEqual(stac.sign_href("HLSS30.v2.0", href), "https://s3.example/presigned?sig=1")
        self.assertEqual(stac.sign_href("HLSS30.v2.0", "https://other.example/x.tif"), "https://other.example/x.tif")

    def test_earthdata_errors_are_explained(self):
        import io
        import urllib.error
        auth.reset()
        self.addCleanup(auth.reset)
        href = "https://data.lpdaac.earthdatacloud.nasa.gov/lp-protected/x.tif"
        with self.assertRaises(auth.AuthError):                                  # بدون اعتبارنامه
            auth.resolve_edl(href, lambda *a, **k: None)
        RUNTIME.apply(cfg_doc(providers={"earthdata": {"enabled": True, "cred": {"token": "TOK"}}}))

        def deny(req, timeout=20):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO())
        with self.assertRaises(auth.AuthError) as e:
            auth.resolve_edl(href, deny)
        self.assertIn("LP DAAC", str(e.exception))
        with mock.patch.object(auth, "_open_noredirect", deny), self.assertRaises(stac.StacError):
            stac.sign_href("HLSS30.v2.0", href)

    def test_token_is_made_from_user_and_password_and_cached(self):
        import io
        auth.reset()
        self.addCleanup(auth.reset)
        RUNTIME.apply(cfg_doc(providers={"earthdata": {"enabled": True, "cred": {"user": "me", "password": "pw"}}}))
        calls = []

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req, timeout=20):
            calls.append((req.full_url, req.get_header("Authorization")))
            return R(b'{"access_token": "GENERATED", "token_type": "Bearer"}')
        self.assertEqual(auth.edl_token(opener), "GENERATED")
        self.assertEqual(auth.edl_token(opener), "GENERATED")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1].startswith("Basic "))
        self.assertIn("find_or_create_token", calls[0][0])


# نام دارایی‌های یک آیتم واقعی Copernicus (STAC v1.1، Sentinel-2 L2A)؛ نام‌های ما باید زیرمجموعه‌ی آن باشد
CDSE_REAL_ASSETS = {"AOT_10m", "AOT_20m", "AOT_60m", "B01_20m", "B01_60m", "B02_10m", "B02_20m", "B02_60m", "B03_10m", "B03_20m", "B03_60m",
                    "B04_10m", "B04_20m", "B04_60m", "B05_20m", "B05_60m", "B06_20m", "B06_60m", "B07_20m", "B07_60m", "B08_10m", "B09_60m",
                    "B11_20m", "B11_60m", "B12_20m", "B12_60m", "B8A_20m", "B8A_60m", "Product", "SCL_20m", "SCL_60m", "TCI_10m", "TCI_20m",
                    "TCI_60m", "WVP_10m", "WVP_20m", "WVP_60m", "thumbnail", "safe_manifest", "granule_metadata", "inspire_metadata",
                    "product_metadata", "datastrip_metadata"}
PC_REAL_ASSETS = {"B02", "B03", "B04", "B05", "B08", "B11", "B12", "B8A", "SCL"}      # آیتم واقعی Planetary Computer (همین‌ها که ما می‌خواهیم)


class CopernicusTests(Base):
    CRED = {"s3_access": "AKIA-TEST", "s3_secret": "SECRET-TEST"}

    def enable(self):
        RUNTIME.apply(cfg_doc(providers={"copernicus": {"enabled": True, "cred": self.CRED}}))

    def test_our_asset_names_exist_in_real_items(self):
        s2 = spec.MISSIONS["sentinel2"]
        cd = s2.source("copernicus")
        self.assertTrue(set(cd.assets.values()) | {cd.mask_asset} <= CDSE_REAL_ASSETS)
        pc = s2.source("planetary")
        for need in (set(pc.assets.values()) - {"B06", "B07"}) | {pc.mask_asset}:       # B06 و B07 در آیتم نمونه‌ی PC کوتاه‌شده نبود
            self.assertIn(need, PC_REAL_ASSETS | {"B06", "B07"})

    def test_sources_need_both_keys_and_come_after_the_open_catalogs(self):
        self.assertEqual([s.provider for s in RUNTIME.sources("sentinel2")], ["earthsearch", "planetary"])
        RUNTIME.apply(cfg_doc(providers={"copernicus": {"enabled": True, "cred": {"s3_access": "A"}}}))
        self.assertEqual([s.provider for s in RUNTIME.sources("sentinel2")], ["earthsearch", "planetary"])      # کلید محرمانه ندارد
        self.enable()
        self.assertEqual([s.provider for s in RUNTIME.sources("sentinel2")], ["earthsearch", "planetary", "copernicus"])
        self.assertEqual([s.provider for s in RUNTIME.sources("s2_l1c")], ["earthsearch", "copernicus"])

    def test_gdal_env_points_at_the_eodata_endpoint(self):
        self.assertEqual(RUNTIME.gdal_env("copernicus"), {})
        self.enable()
        env = RUNTIME.gdal_env("copernicus")
        self.assertEqual((env["AWS_S3_ENDPOINT"], env["AWS_ACCESS_KEY_ID"], env["AWS_VIRTUAL_HOSTING"]),
                         ("eodata.dataspace.copernicus.eu", "AKIA-TEST", "FALSE"))
        self.assertEqual(env["GDAL_DISABLE_READDIR_ON_OPEN"], "EMPTY_DIR")
        self.assertEqual(RUNTIME.gdal_env("earthsearch"), {})
        import os

        import rasterio
        self.assertEqual(os.environ["AWS_S3_ENDPOINT"], "eodata.dataspace.copernicus.eu")          # کلید AWS فقط متغیر محیطی فرایند
        self.assertEqual(os.environ["AWS_ACCESS_KEY_ID"], "AKIA-TEST")
        with RUNTIME.env("copernicus"):                                                           # گزینه‌های غیر AWS از راه Env
            self.assertEqual(rasterio.env.getenv()["GDAL_DISABLE_READDIR_ON_OPEN"], "EMPTY_DIR")
        RUNTIME.reset()                                                                           # پاک‌سازی: کلید در محیط نماند
        self.assertNotIn("AWS_ACCESS_KEY_ID", os.environ)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", os.environ)

    def test_other_aws_variables_of_the_operator_are_left_alone(self):
        import os
        with mock.patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "OPERATOR-OWN"}):
            RUNTIME.apply(cfg_doc())                                                              # بدون اعتبارنامه‌ی Copernicus
            self.assertEqual(os.environ["AWS_ACCESS_KEY_ID"], "OPERATOR-OWN")
            self.enable()
            self.assertEqual(os.environ["AWS_ACCESS_KEY_ID"], "AKIA-TEST")

    def test_eodata_hrefs_stay_s3_and_others_become_https(self):
        self.assertEqual(spec.https_href("s3://eodata/Sentinel-2/x.jp2"), "s3://eodata/Sentinel-2/x.jp2")
        self.assertEqual(spec.https_href("s3://sentinel-cogs/x.tif"), "https://sentinel-cogs.s3.amazonaws.com/x.tif")

    def make_cdse(self, nir=4000, red=2000) -> dict:
        """آیتم ساختگی با نام‌های واقعی CDSE و فایل‌های JP2 واقعی (۱۰ و ۲۰ متر)."""
        w, s, e, n = transform_bounds("EPSG:4326", "EPSG:32639", 51.2, 35.6, 51.45, 35.85)
        ox, oy = int(w // 20 * 20), int(n // 20 * 20)
        assets = {}
        for key, v in {"B04_10m": red, "B03_10m": 1200, "B02_10m": 900, "B08_10m": nir, "B05_20m": 1500, "B06_20m": 1700, "B07_20m": 1800,
                       "B8A_20m": 2900, "B11_20m": 2000, "B12_20m": 1600}.items():
            res = int(key.split("_")[1][:-1])
            size = int((e - w) / res) + 2, int((n - s) / res) + 2
            path = self.root / f"{key}.jp2"
            with rasterio.open(path, "w", driver="JP2OpenJPEG", width=size[0], height=size[1], count=1, dtype="uint16", crs="EPSG:32639",
                               transform=from_origin(ox, oy, res, res)) as dst:
                dst.write(np.full((size[1], size[0]), v, dtype="uint16"), 1)
            assets[key] = {"href": str(path), "type": "image/jp2"}
        sz = int((e - w) / 20) + 2, int((n - s) / 20) + 2
        scl = np.full((sz[1], sz[0]), 4, dtype="uint8")
        scl[: sz[1] // 2, :] = 9                                                          # نیمه‌ی شمالی ابر
        sp = self.root / "SCL_20m.jp2"
        with rasterio.open(sp, "w", driver="JP2OpenJPEG", width=sz[0], height=sz[1], count=1, dtype="uint8", crs="EPSG:32639",
                           transform=from_origin(ox, oy, 20, 20)) as dst:
            dst.write(scl, 1)
        assets["SCL_20m"] = {"href": str(sp), "type": "image/jp2"}
        return {"id": "S2C_MSIL2A_20260601T070001_N0511_R122_T39SUQ_20260601T100000", "collection": "sentinel-2-l2a", "assets": assets,
                "properties": {"datetime": "2026-06-01T07:00:01Z", "eo:cloud_cover": 20, "platform": "sentinel-2c"}}

    def test_jp2_scene_with_mixed_resolutions_builds_ndvi_and_masks_clouds(self):
        item = self.make_cdse()
        cd = spec.MISSIONS["sentinel2"].source("copernicus")
        out = process.build_scene(item, "sentinel2", "ndvi", BBOX, self.root / "cd.tif", mask=False, source=cd)
        with rasterio.open(out) as ds:
            self.assertAlmostEqual(float(ds.read(1).mean()), 0.5, places=2)
        out = process.build_scene(item, "sentinel2", "allbands", BBOX, self.root / "all.tif", mask=True, source=cd)
        with rasterio.open(out) as ds:
            self.assertEqual(ds.count, 10)
        comp, used = process.build_composite([item], "sentinel2", "ndvi", BBOX, self.root / "comp.tif", mask=True, source=cd)
        self.assertEqual(used, 1)
        with rasterio.open(comp) as ds:
            data = ds.read(1)
            self.assertTrue((data == -9999).any() and (data != -9999).any())                  # ابر ماسک شد، بقیه ماند

    def test_scene_cards_have_no_thumbnail_for_copernicus(self):
        self.enable()
        feat = {"id": "S2C_X", "collection": "sentinel-2-l2a", "geometry": FULL, "properties": {"datetime": "2026-06-01T07:00:00Z"},
                "assets": {"thumbnail": {"href": "https://datahub.creodias.eu/odata/v1/Assets(x)/$value", "type": "image/jpeg"}}}

        def fetch(url, body=None, timeout=30):
            if "dataspace" in url:
                return {"features": [feat]}
            return {"features": []}
        res = stac.search(BBOX, "2026-06-01", "2026-06-30", fetch=fetch, source="copernicus")
        self.assertEqual((res[0]["source"], res[0]["thumb"]), ("copernicus", False))
        self.assertEqual(RUNTIME.provider_url("copernicus"), "https://stac.dataspace.copernicus.eu/v1")

    def test_probe_opens_a_band_with_gdal_not_the_thumbnail(self):
        self.enable()
        m = spec.MISSIONS["sentinel2"]
        src = m.source("copernicus")
        feat = {"id": "X", "assets": {**{a: {"href": f"s3://eodata/x/{a}.jp2"} for a in (*src.assets.values(), src.mask_asset)},
                                      "thumbnail": {"href": "https://datahub.creodias.eu/x", "type": "image/jpeg"}}}
        opened = []
        with mock.patch.object(stac, "_gdal_head", lambda href: opened.append(href) or b"10980x10980"):
            r = stac.check_source(m, src, lambda *a, **k: {"features": [feat]}, strict=True)
        self.assertTrue(r["ok"], r)
        self.assertEqual(opened, ["s3://eodata/x/B04_10m.jp2"])

    def test_gdal_head_explains_missing_key_and_denied_access(self):
        with self.assertRaises(stac.StacError) as e:
            stac._gdal_head("s3://eodata/x.jp2")
        self.assertIn("کلید", str(e.exception))
        self.enable()
        import rasterio

        def denied(*a, **k):
            raise rasterio.errors.RasterioIOError("HTTP response code: 403 InvalidAccessKeyId")
        with mock.patch("rasterio.open", denied), self.assertRaises(stac.StacError) as e:
            stac._gdal_head("s3://eodata/x.jp2")
        self.assertIn("رد شد", str(e.exception))
        self.assertNotIn("SECRET-TEST", str(e.exception))

    def test_job_runs_inside_the_s3_env(self):
        self.enable()
        item = self.make_cdse()
        seen = []
        real = process.build_scene

        def spy(*a, **k):
            import os

            import rasterio
            seen.append((os.environ.get("AWS_S3_ENDPOINT"), rasterio.env.getenv().get("GDAL_DISABLE_READDIR_ON_OPEN")))
            return real(*a, **k)
        cfg = Config({"SATGATE_SECRET": SECRET, "SATGATE_PANEL_URL": "https://panel.test", "SATGATE_DATA": str(self.root / "d"),
                      "SATGATE_MAX_KM2": "200", "SATGATE_WORKERS": "1"})
        gw = Gateway(cfg, fetch=lambda url, body=None, timeout=30: item if "/items/" in url else {"features": []}, post=lambda p, b: None)
        gw.notify = lambda job: None
        self.addCleanup(gw.pool.shutdown, True)
        gw.store.put({"id": "7" * 32, "status": "queued", "product": "ndvi", "mission": "sentinel2", "bbox": BBOX, "scene": item["id"],
                      "created": int(time.time()), "message": "", "mask": False, "composite": None, "source": "copernicus"})
        with mock.patch("satgate.app.build_scene", spy):
            gw.run("7" * 32)
        self.assertEqual(gw.store.get("7" * 32)["status"], "ready", gw.store.get("7" * 32))
        self.assertEqual(seen, [("eodata.dataspace.copernicus.eu", "EMPTY_DIR")])


class PalsarTests(Base):
    def test_digital_numbers_become_decibels(self):
        t1 = tile(self.root / "p1.tif", 51.25, 35.65, 0.1, 1000, dtype="uint16", nodata=0)
        t2 = tile(self.root / "p2.tif", 51.35, 35.65, 0.1, 0, dtype="uint16", nodata=0)                  # بی‌داده
        items = [{"id": "a", "assets": {"HV": {"href": t1}}}, {"id": "b", "assets": {"HV": {"href": t2}}}]
        out = process.build_layer(items, "palsar_hv", [51.30, 35.70, 51.40, 35.73], self.root / "hv.tif")
        with rasterio.open(out) as ds:
            data = ds.read(1)
            self.assertEqual((ds.dtypes[0], ds.nodata), ("float32", -9999.0))
            vals = np.unique(np.round(data, 3))
            self.assertIn(-23.0, vals)                                  # ‎20·log10(1000) − 83
            self.assertIn(-9999.0, vals)
            self.assertEqual(ds.descriptions[0], "palsar_hv")

    def test_all_nodata_is_an_error(self):
        t = tile(self.root / "z.tif", 51.2, 35.6, 0.3, 0, dtype="uint16", nodata=0)
        with self.assertRaises(process.ProcessError):
            process.build_layer([{"assets": {"HH": {"href": t}}}], "palsar_hh", BBOX, self.root / "z_out.tif")

    def test_layer_search_uses_the_fixed_year(self):
        bodies = []

        def fetch(url, body=None, timeout=30):
            bodies.append(body)
            return {"features": [{"id": "t", "assets": {"HH": {"href": "x"}}}]}
        stac.layer_items(spec.MISSIONS["palsar_hh"], BBOX, fetch)
        self.assertEqual(bodies[0]["collections"], ["alos-palsar-mosaic"])
        self.assertEqual(bodies[0]["datetime"], "2020-01-01T00:00:00Z/2020-12-31T23:59:59Z")


def tiff_bytes(value=1500, dtype="int16", nodata=-32768, size=20) -> bytes:
    from rasterio.io import MemoryFile
    with MemoryFile() as mf:
        with mf.open(driver="GTiff", width=size, height=size, count=1, dtype=dtype, crs="EPSG:4326",
                     transform=from_origin(51.29, 35.72, 0.001, 0.001), nodata=nodata) as dst:
            arr = np.full((size, size), value, dtype=dtype)
            arr[0, 0] = nodata
            dst.write(arr, 1)
        return mf.read()


class OpenTopographyTests(Base):
    def fake(self, body: bytes, calls=None):
        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req, timeout=0):
            if calls is not None:
                calls.append(req.full_url)
            return R(body)
        return opener

    def test_url_has_all_parameters_and_download_checks_magic(self):
        calls = []
        dest = self.root / "o.tif"
        n = otapi.fetch_geotiff("SRTMGL1", BBOX, "KEY123", "https://portal.opentopography.org/API", dest, self.fake(tiff_bytes(), calls))
        self.assertGreater(n, 100)
        self.assertIn("demtype=SRTMGL1", calls[0])
        self.assertIn("south=35.700000", calls[0])
        self.assertIn("outputFormat=GTiff", calls[0])
        self.assertIn("API_Key=KEY123", calls[0])
        with self.assertRaises(otapi.OTError) as e:
            otapi.fetch_geotiff("SRTMGL1", BBOX, "K", "https://x.example/API", self.root / "bad.tif", self.fake(b"<html>error</html>"))
        self.assertFalse((self.root / "bad.tif").exists())
        self.assertNotIn("K", str(e.exception).replace("OpenTopography", "").replace("درخواست", ""))
        with self.assertRaises(otapi.OTError):
            otapi.fetch_geotiff("SRTMGL1", BBOX, "", "https://x.example/API", self.root / "n.tif")        # بدون کلید

    def test_http_errors_are_mapped_and_never_leak_the_key(self):
        import urllib.error
        for code, word in ((401, "نامعتبر"), (403, "اجازه"), (204, "ندارد"), (400, "رد کرد"), (429, "سهمیه"), (500, "۵۰۰".replace("۵۰۰", "500"))):
            def opener(req, timeout=0, code=code):
                raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO())
            with self.assertRaises(otapi.OTError) as e:
                otapi.fetch_geotiff("COP30", BBOX, "SECRETKEY", "https://x.example/API", self.root / "e.tif", opener)
            self.assertIn(word, str(e.exception))
            self.assertNotIn("SECRETKEY", str(e.exception))

        def down(req, timeout=0):
            raise urllib.error.URLError("boom SECRETKEY")
        with self.assertRaises(otapi.OTError) as e:
            otapi.fetch_geotiff("COP30", BBOX, "SECRETKEY", "https://x.example/API", self.root / "e.tif", down)
        self.assertNotIn("SECRETKEY", str(e.exception))

    def test_size_cap(self):
        with self.assertRaises(otapi.OTError):
            otapi.fetch_geotiff("COP30", BBOX, "K", "https://x.example/API", self.root / "big.tif", self.fake(tiff_bytes(size=200)), max_bytes=500)

    def test_raw_geotiff_becomes_float32_with_minus_9999(self):
        raw = self.root / "raw.tif"
        raw.write_bytes(tiff_bytes(1500))
        out = process.build_layer_from_file(raw, "srtm30", self.root / "out.tif")
        with rasterio.open(out) as ds:
            data = ds.read(1)
            self.assertEqual((ds.dtypes[0], ds.nodata), ("float32", -9999.0))
            self.assertEqual(float(data[0, 0]), -9999.0)
            self.assertAlmostEqual(float(data[5, 5]), 1500.0)
        empty = self.root / "empty.tif"
        empty.write_bytes(tiff_bytes(-32768))
        with self.assertRaises(process.ProcessError):
            process.build_layer_from_file(empty, "bathy", self.root / "e.tif")

    def test_probe_and_check_source(self):
        RUNTIME.apply(cfg_doc(providers={"opentopography": {"enabled": True, "cred": {"api_key": "K"}}}))
        with mock.patch.object(otapi, "probe", lambda *a, **k: 5000):
            r = stac.check_mission("srtm30", strict=True)
        self.assertTrue(r["ok"], r)

        def bad(*a, **k):
            raise otapi.OTError("کلید OpenTopography نامعتبر است.")
        with mock.patch.object(otapi, "probe", bad):
            r = stac.check_mission("srtm30", strict=True)
        self.assertEqual((r["ok"], r["error"]), (False, "کلید OpenTopography نامعتبر است."))

    def gateway(self, fetch):
        cfg = Config({"SATGATE_SECRET": SECRET, "SATGATE_PANEL_URL": "https://panel.test", "SATGATE_DATA": str(self.root / "d"),
                      "SATGATE_MAX_KM2": "200", "SATGATE_WORKERS": "1"})
        gw = Gateway(cfg, fetch=fetch, post=lambda path, body: None)
        gw.notify = lambda job: None
        self.addCleanup(gw.pool.shutdown, True)
        return gw

    def run_job(self, gw, mission, jid="9" * 32):
        gw.store.put({"id": jid, "status": "queued", "product": mission, "mission": mission, "bbox": BBOX, "scene": "", "created": int(time.time()),
                      "message": "", "mask": False, "composite": None, "source": ""})
        gw.run(jid)
        return gw.store.get(jid)

    def test_layer_falls_back_to_opentopography_when_catalogs_fail(self):
        RUNTIME.apply(cfg_doc(providers={"opentopography": {"enabled": True, "cred": {"api_key": "K"}}}))

        def down(url, body=None, timeout=30):
            raise stac.StacError("وصل نشدیم")
        gw = self.gateway(down)
        with mock.patch("urllib.request.urlopen", side_effect=self.fake(tiff_bytes(900))):
            job = self.run_job(gw, "dem")
        self.assertEqual(job["status"], "ready", job)
        with rasterio.open(gw.store.file("9" * 32)) as ds:
            self.assertEqual((ds.dtypes[0], round(float(ds.read(1)[5, 5]))), ("float32", 900))
        self.assertFalse(list((self.root / "d").rglob("*.raw")))             # فایل خام پاک شد

    def test_opentopography_only_layer_and_error_message(self):
        RUNTIME.apply(cfg_doc(providers={"opentopography": {"enabled": True, "cred": {"api_key": "K"}}}))
        gw = self.gateway(lambda *a, **k: {"features": []})
        with mock.patch("urllib.request.urlopen", side_effect=self.fake(tiff_bytes(-300))):
            job = self.run_job(gw, "bathy")
        self.assertEqual(job["status"], "ready", job)
        import urllib.error

        def deny(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 401, "x", {}, io.BytesIO())
        with mock.patch("urllib.request.urlopen", side_effect=deny):
            job = self.run_job(gw, "srtm30", "8" * 32)
        self.assertEqual(job["status"], "failed")
        self.assertIn("کلید OpenTopography نامعتبر", job["message"])
        self.assertNotIn("API_Key", job["message"])

    def test_layer_without_key_is_off(self):
        gw = self.gateway(lambda *a, **k: {"features": []})
        job = self.run_job(gw, "srtm30")
        self.assertEqual(job["status"], "failed")
        self.assertIn("خاموش", job["message"])


if __name__ == "__main__":
    unittest.main()
