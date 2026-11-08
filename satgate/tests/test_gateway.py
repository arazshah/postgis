import hashlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

from satgate import protocol, spec, stac
from satgate.app import Config, Gateway, make_app

BBOX = [51.30, 35.70, 51.34, 35.73]   # حدود ۳٫۶ در ۳٫۳ کیلومتر، نزدیک تهران
SECRET = "test-secret"


def make_scene(root: Path, nir_v=3000, red_v=1000) -> dict:
    """تصویر ساختگی Sentinel-2: چهار باند ۱۰ متری و یک باند ۲۰ متری روی UTM 39N."""
    w, s, e, n = transform_bounds("EPSG:4326", "EPSG:32639", 51.2, 35.6, 51.45, 35.85)
    ox, oy = int(w // 10 * 10), int(n // 10 * 10)
    assets = {}
    vals = {"red": red_v, "green": 1200, "blue": 900, "nir": nir_v, "rededge1": 1500, "rededge2": 1700,
            "rededge3": 1800, "nir08": 2900, "swir16": 2000, "swir22": 1600}
    for name, v in vals.items():
        res = 20 if name in ("rededge1", "rededge2", "rededge3", "nir08", "swir16", "swir22") else 10
        size = int((e - w) / res) + 2, int((n - s) / res) + 2
        path = root / f"{name}.tif"
        with rasterio.open(path, "w", driver="GTiff", width=size[0], height=size[1], count=1, dtype="uint16",
                           crs="EPSG:32639", transform=from_origin(ox, oy, res, res)) as dst:
            dst.write(np.full((size[1], size[0]), v, dtype="uint16"), 1)
        assets[name] = {"href": str(path), "raster:bands": [{"scale": 0.0001, "offset": -0.1}]}
    return {"id": "S2A_39SUQ_20260601_0_L2A", "collection": "sentinel-2-l2a", "assets": assets,
            "properties": {"datetime": "2026-06-01T07:00:00Z", "eo:cloud_cover": 3.2}}


def make_landsat(root: Path, nir_dn=20000, red_dn=15000) -> dict:
    """تصویر ساختگی Landsat 8/9 Collection 2 Level-2: شش باند ۳۰ متری، scale=2.75e-5 و offset=-0.2."""
    w, s, e, n = transform_bounds("EPSG:4326", "EPSG:32639", 51.1, 35.5, 51.55, 35.95)
    ox, oy = int(w // 30 * 30), int(n // 30 * 30)
    size = int((e - w) / 30) + 2, int((n - s) / 30) + 2
    assets = {}
    for name, v in {"red": red_dn, "green": 14000, "blue": 12000, "nir08": nir_dn, "swir16": 16000, "swir22": 13000}.items():
        path = root / f"ls_{name}.tif"
        with rasterio.open(path, "w", driver="GTiff", width=size[0], height=size[1], count=1, dtype="uint16",
                           crs="EPSG:32639", transform=from_origin(ox, oy, 30, 30)) as dst:
            dst.write(np.full((size[1], size[0]), v, dtype="uint16"), 1)
        assets[name] = {"href": str(path), "raster:bands": [{"scale": 2.75e-05, "offset": -0.2}]}
    return {"id": "LC09_L2SP_164035_20261020_20261022_02_T1", "collection": "landsat-c2-l2", "assets": assets,
            "properties": {"datetime": "2026-10-20T07:10:00Z", "eo:cloud_cover": 4.0, "platform": "landsat-9"}}


class ProtocolTests(unittest.TestCase):
    def test_sign_and_verify(self):
        h = protocol.sign("k", "POST", "/v1/jobs", b'{"a":1}')
        self.assertTrue(protocol.verify("k", "POST", "/v1/jobs", b'{"a":1}', h[protocol.H_TIME], h[protocol.H_SIG]))

    def test_rejects_tamper_wrong_key_and_old_time(self):
        h = protocol.sign("k", "POST", "/v1/jobs", b"x")
        t, s = h[protocol.H_TIME], h[protocol.H_SIG]
        self.assertFalse(protocol.verify("k", "POST", "/v1/jobs", b"y", t, s))
        self.assertFalse(protocol.verify("k", "GET", "/v1/jobs", b"x", t, s))
        self.assertFalse(protocol.verify("other", "POST", "/v1/jobs", b"x", t, s))
        self.assertFalse(protocol.verify("", "POST", "/v1/jobs", b"x", t, s))
        old = protocol.sign("k", "POST", "/p", b"", ts=time.time() - 600)
        self.assertFalse(protocol.verify("k", "POST", "/p", b"", old[protocol.H_TIME], old[protocol.H_SIG]))


class CheckReasonTests(unittest.TestCase):
    """علت دقیق رد شدن: ساعت، کلید، مسیر/بدنه یا امضای نبود."""

    def chk(self, secret="k", **kw):
        h = protocol.sign("k", "POST", "/v1/jobs", b"x", ts=kw.pop("ts", None))
        return protocol.check(secret, "POST", kw.pop("target", "/v1/jobs"), kw.pop("body", b"x"), h[protocol.H_TIME],
                              kw.pop("sig", h[protocol.H_SIG]), kw.pop("kid", h[protocol.H_KID]))

    def test_ok(self):
        self.assertEqual(self.chk().reason, "ok")

    def test_clock_skew_reports_direction_and_seconds(self):
        c = self.chk(ts=time.time() + 600)
        self.assertEqual((c.reason, c.ok), ("skew", False))
        self.assertAlmostEqual(c.skew_s, 600, delta=3)
        self.assertLess(self.chk(ts=time.time() - 900).skew_s, 0)

    def test_wrong_key_is_named_not_just_bad_signature(self):
        self.assertEqual(self.chk(secret="other").reason, "key")

    def test_same_key_but_tampered_path_or_body_is_signature(self):
        self.assertEqual(self.chk(target="/v1/other").reason, "signature")
        self.assertEqual(self.chk(body=b"y").reason, "signature")

    def test_missing_and_no_secret(self):
        self.assertEqual(protocol.check("k", "GET", "/", b"", None, None).reason, "missing")
        self.assertEqual(self.chk(secret="").reason, "no_secret")

    def test_old_sender_without_kid_still_checked_by_signature(self):
        self.assertEqual(self.chk(secret="other", kid=None).reason, "signature")
        self.assertEqual(self.chk(kid=None).reason, "ok")

    def test_key_id_is_short_and_salted(self):
        self.assertEqual(len(protocol.key_id("k")), 8)
        self.assertNotEqual(protocol.key_id("k"), hashlib.sha256(b"k").hexdigest()[:8])


class SpecTests(unittest.TestCase):
    def test_area_and_estimate(self):
        self.assertAlmostEqual(spec.area_km2([51, 35, 52, 36]), 111.32 * 111.32 * 0.8139, delta=60)
        small = spec.estimate_bytes(BBOX, "true_color")
        big = spec.estimate_bytes([51.0, 35.0, 51.4, 35.4], "true_color")
        self.assertGreater(big, small * 50)
        self.assertGreater(spec.estimate_bytes(BBOX, "allbands"), spec.estimate_bytes(BBOX, "true_color") * 4)

    def test_bbox_validation(self):
        self.assertTrue(spec.valid_bbox(BBOX))
        for bad in (None, [1, 2, 3], [5, 0, 1, 1], [0, 0, 1, 91], ["a", 0, 1, 1], [0, 0, float("nan"), 1]):
            self.assertFalse(spec.valid_bbox(bad))


class SatelliteNameTests(unittest.TestCase):
    def test_names_from_scene_ids(self):
        self.assertEqual(spec.satellite_of("S2B_38SMG_20261024_0_L2A"), ("Sentinel-2B", "ESA / Copernicus"))
        self.assertEqual(spec.satellite_of("S2C_38SMG_20261009_0_L2A")[0], "Sentinel-2C")
        self.assertEqual(spec.satellite_of("LC08_L2SP_164035_20260101_02_T1")[0], "Landsat 8")
        self.assertEqual(spec.satellite_of("LC09_L2SP_164035_20260101_02_T1")[0], "Landsat 9")
        self.assertEqual(spec.satellite_of("cop-dem-glo-30")[0], "Copernicus DEM GLO-30")
        self.assertEqual(spec.satellite_of("whatever"), ("", ""))
        self.assertEqual(spec.satellite_of(""), ("", ""))

    def test_search_results_carry_satellite(self):
        full = {"type": "Polygon", "coordinates": [[[51, 35], [52, 35], [52, 36], [51, 36], [51, 35]]]}
        feats = [{"id": "S2A_39SUQ_20260601_0_L2A", "geometry": full, "properties": {"datetime": "2026-06-01T00:00:00Z"}}]
        res = stac.search(BBOX, "2026-06-01", "2026-06-30", fetch=lambda *a, **k: {"features": feats})
        self.assertEqual((res[0]["satellite"], res[0]["agency"]), ("Sentinel-2A", "ESA / Copernicus"))


class ThumbTests(unittest.TestCase):
    """پیش‌نمایش هر ماهواره: نام دارایی بین مجموعه‌ها فرق دارد و فقط https تصویری پذیرفته می‌شود."""

    def test_asset_choice(self):
        t = {"href": "https://a/t.jpg", "type": "image/jpeg"}
        self.assertIs(stac.thumb_asset({"assets": {"thumbnail": t, "rendered_preview": {"href": "https://a/p.png"}}}), t)
        p = {"href": "https://pc/api/data/v1/item/preview.png?x=1", "type": "image/png"}
        self.assertIs(stac.thumb_asset({"assets": {"rendered_preview": p}}), p)
        self.assertIsNone(stac.thumb_asset({"assets": {"thumbnail": {"href": "http://a/t.jpg"}}}))          # فقط https
        self.assertIsNone(stac.thumb_asset({"assets": {"thumbnail": {"href": "https://a/x", "type": "application/json"}}}))
        self.assertIsNone(stac.thumb_asset({"assets": {}}))
        self.assertIsNone(stac.thumb_asset({}))

    def test_scene_flag_follows_any_preview_asset(self):
        full = {"type": "Polygon", "coordinates": [[[51, 35], [52, 35], [52, 36], [51, 36], [51, 35]]]}
        it = {"id": "LC09_L2SP_164035_20261020_20261022_02_T1", "geometry": full, "properties": {"datetime": "2026-10-20T00:00:00Z"},
              "assets": {"rendered_preview": {"href": "https://pc/p.png", "type": "image/png"}}}
        res = stac.search(BBOX, "2026-10-01", "2026-10-30", fetch=lambda *a, **k: {"features": [it]}, mission="landsat")
        self.assertTrue(res[0]["thumb"])
        self.assertEqual(res[0]["collection"], "landsat-c2-l2")

    def test_gateway_thumb_for_landsat_is_signed_and_cached(self):
        import tempfile as tf
        from unittest import mock
        with tf.TemporaryDirectory() as d:
            gw = Gateway(Config({"SATGATE_SECRET": SECRET, "SATGATE_DATA": d}), fetch=None)
            stac._TOKENS.clear()
            az = "https://landsateuwest.blob.core.windows.net/landsat-c2/x_thumb.jpeg"

            def fetch(url, body=None, timeout=30):
                if "sas/v1/token" in url:
                    return {"token": "sig=z", "msft:expiry": "2099-01-01T00:00:00Z"}
                return {"assets": {"thumbnail": {"href": az, "type": "image/jpeg"}}}
            gw.fetch = fetch
            seen = []

            class R:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def read(self, n=-1):
                    return b"\xff\xd8jpg"
            with mock.patch("urllib.request.urlopen", side_effect=lambda req, timeout=0: (seen.append(req.full_url), R())[1]):
                self.assertEqual(gw.thumb("landsat-c2-l2", "LC09_L2SP_164035_20261020_20261022_02_T1"), b"\xff\xd8jpg")
                gw.thumb("landsat-c2-l2", "LC09_L2SP_164035_20261020_20261022_02_T1")
            self.assertEqual(seen, [az + "?sig=z"])                 # توکن اضافه شد و بار دوم از کش
            self.assertIsNone(gw.thumb("other-collection", "ABC123"))
            self.assertIsNone(gw.thumb("landsat-c2-l2", "../etc/passwd"))


class LandsatTests(unittest.TestCase):
    """Landsat: وضوح ۳۰ متر، نگاشت باند nir←nir08، مقیاس خود دارایی، توکن فقط برای Azure."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.item = make_landsat(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ndvi_uses_nir08_and_asset_scale(self):
        from satgate.process import build_scene
        out = build_scene(self.item, "landsat", "ndvi", BBOX, self.root / "nd.tif")
        # nir=(20000*2.75e-5-.2)=.35  red=(15000*2.75e-5-.2)=.2125 → (.35-.2125)/(.5625)=.2444
        with rasterio.open(out) as r:
            self.assertEqual((r.count, r.dtypes[0]), (1, "float32"))
            self.assertAlmostEqual(r.res[0], 30, places=3)
            self.assertAlmostEqual(float(r.read(1).mean()), 0.2444, places=3)

    def test_true_color_and_allbands(self):
        from satgate.process import build_scene
        tc = build_scene(self.item, "landsat", "true_color", BBOX, self.root / "tc.tif")
        with rasterio.open(tc) as r:
            self.assertEqual((r.count, r.dtypes[0], r.nodata), (3, "uint8", 0))
            self.assertTrue((r.read() > 0).all())
        al = build_scene(self.item, "landsat", "allbands", BBOX, self.root / "all.tif")
        with rasterio.open(al) as r:
            self.assertEqual((r.count, r.dtypes[0]), (6, "uint16"))
            self.assertEqual(r.descriptions[3], "nir")

    def test_missing_asset_named_by_stac_key(self):
        from satgate.process import ProcessError, build_scene
        del self.item["assets"]["nir08"]
        with self.assertRaises(ProcessError) as cm:
            build_scene(self.item, "landsat", "ndvi", BBOX, self.root / "x.tif")
        self.assertIn("nir08", str(cm.exception))

    def test_products_and_estimates_differ_per_mission(self):
        self.assertEqual(spec.get_product("landsat", "allbands").bands, ("red", "green", "blue", "nir", "swir16", "swir22"))
        self.assertEqual(spec.get_product("sentinel2", "allbands").res_m, 10)
        self.assertEqual(spec.get_product("landsat", "true_color").res_m, 30)
        self.assertEqual(spec.get_product("anything", "dem").key, "dem")
        self.assertIsNone(spec.get_product("landsat", "nope"))
        big = [51.0, 35.5, 51.4, 35.9]
        self.assertLess(spec.estimate_bytes(big, "true_color", "landsat"), spec.estimate_bytes(big, "true_color", "sentinel2") / 5)

    def test_search_filters_platform_and_uses_planetary_computer(self):
        seen = {}

        def fake(url, body=None, timeout=30):
            seen.update(url=url, body=body)
            return {"features": []}
        stac.search(BBOX, "2026-06-01", "2026-06-30", 20, fetch=fake, mission="landsat")
        self.assertIn("planetarycomputer", seen["url"])
        self.assertEqual(seen["body"]["collections"], ["landsat-c2-l2"])
        self.assertEqual(seen["body"]["query"]["platform"], {"in": ["landsat-8", "landsat-9"]})
        with self.assertRaises(stac.StacError):
            stac.search(BBOX, "a", "b", fetch=fake, mission="nope")

    def test_token_signs_only_azure_landsat_hrefs_and_is_cached(self):
        stac._TOKENS.clear()
        calls = []

        def fake(url, body=None, timeout=30):
            calls.append(url)
            return {"token": "sig=abc&se=2099", "msft:expiry": "2099-01-01T00:00:00Z"}
        az = "https://landsateuwest.blob.core.windows.net/landsat-c2/x/red.tif"
        self.assertEqual(stac.sign_href("landsat-c2-l2", az, fake), az + "?sig=abc&se=2099")
        self.assertEqual(stac.sign_href("landsat-c2-l2", az + "?a=1", fake), az + "?a=1&sig=abc&se=2099")
        self.assertEqual(len(calls), 1)    # توکن کش شد
        other = "https://sentinel-cogs.s3.us-west-2.amazonaws.com/x.tif"
        self.assertEqual(stac.sign_href("sentinel-2-l2a", other, fake), other)
        self.assertEqual(stac.sign_href("landsat-c2-l2", other, fake), other)
        self.assertEqual(stac.sign_href("landsat-c2-l2", "/local/path.tif", fake), "/local/path.tif")

    def test_check_mission_reports_ok_and_reason(self):
        ok = stac.check_mission("sentinel2", fetch=lambda *a, **k: {"features": []})
        self.assertTrue(ok["ok"])

        def boom(*a, **k):
            raise stac.StacError("به کاتالوگ تصویر وصل نشدیم.")
        bad = stac.check_mission("landsat", fetch=boom)
        self.assertEqual((bad["ok"], bad["error"]), (False, "به کاتالوگ تصویر وصل نشدیم."))
        feat = {"features": [{"assets": {"thumbnail": {"href": "https://x.example/t.jpg"}}}]}
        self.assertTrue(stac.check_mission("sentinel2", fetch=lambda *a, **k: feat, open_url=lambda h: b"jpg")["ok"])
        self.assertFalse(stac.check_mission("sentinel2", fetch=lambda *a, **k: feat, open_url=lambda h: b"")["ok"])


class StacTests(unittest.TestCase):
    def test_coverage_full_partial_none(self):
        poly = {"type": "Polygon", "coordinates": [[[51.0, 35.0], [52.0, 35.0], [52.0, 36.0], [51.0, 36.0], [51.0, 35.0]]]}
        self.assertEqual(stac.coverage(poly, [51.1, 35.1, 51.2, 35.2]), 100.0)
        self.assertEqual(stac.coverage(poly, [50.9, 35.1, 51.1, 35.3]), 50.0)
        self.assertEqual(stac.coverage(poly, [60, 35, 61, 36]), 0.0)

    def test_search_sorts_full_coverage_first(self):
        full = {"type": "Polygon", "coordinates": [[[51, 35], [52, 35], [52, 36], [51, 36], [51, 35]]]}
        half = {"type": "Polygon", "coordinates": [[[51.31, 35], [52, 35], [52, 36], [51.31, 36], [51.31, 35]]]}
        feats = [{"id": "new-half", "geometry": half, "properties": {"datetime": "2026-06-10T00:00:00Z", "eo:cloud_cover": 1}},
                 {"id": "old-full", "geometry": full, "properties": {"datetime": "2026-06-01T00:00:00Z", "eo:cloud_cover": 5},
                  "assets": {"thumbnail": {"href": "https://a/t.jpg", "type": "image/jpeg"}}}]
        seen = {}

        def fake(url, body=None, timeout=30):
            seen.update(body=body)
            return {"features": feats}
        res = stac.search(BBOX, "2026-06-01", "2026-06-30", 20, fetch=fake)
        self.assertEqual([s["id"] for s in res], ["old-full", "new-half"])
        self.assertTrue(res[0]["thumb"])
        self.assertEqual(seen["body"]["query"], {"eo:cloud_cover": {"lte": 20.0}})
        with self.assertRaises(stac.StacError):
            stac.search([1, 2], "a", "b", fetch=fake)


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.item = make_scene(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_true_color_is_byte_rgb(self):
        from satgate.process import build_s2
        out = build_s2(self.item, "true_color", BBOX, self.root / "tc.tif")
        with rasterio.open(out) as r:
            self.assertEqual((r.count, r.dtypes[0], r.nodata), (3, "uint8", 0))
            a = r.read()
            self.assertTrue((a > 0).all())
            self.assertGreater(r.width, 200)

    def test_ndvi_value(self):
        from satgate.process import build_s2
        out = build_s2(self.item, "ndvi", BBOX, self.root / "nd.tif")
        with rasterio.open(out) as r:
            self.assertEqual((r.count, r.dtypes[0]), (1, "float32"))
            # بازتاب: nir=(3000-1000)/1e4=.2 ، red=0 → NDVI=1؛ قرمز DN=1000 یعنی بازتاب صفر
            self.assertAlmostEqual(float(r.read(1).mean()), 1.0, places=3)

    def test_allbands_resamples_20m_to_10m(self):
        from satgate.process import build_s2
        out = build_s2(self.item, "allbands", BBOX, self.root / "all.tif")
        with rasterio.open(out) as r:
            self.assertEqual((r.count, r.dtypes[0]), (10, "uint16"))
            self.assertAlmostEqual(r.res[0], 10, places=3)
            self.assertEqual(int(r.read(1)[5, 5]), 1)   # قرمز: DN=1000 → بازتاب صفر → کمینه‌ی ۱ (صفر یعنی بدون داده)
            self.assertGreaterEqual(int(r.read(2)[5, 5]), 1)

    def test_missing_band_and_tiny_bbox(self):
        from satgate.process import ProcessError, build_s2
        del self.item["assets"]["nir"]
        with self.assertRaises(ProcessError):
            build_s2(self.item, "ndvi", BBOX, self.root / "x.tif")
        self.item = make_scene(self.root)
        with self.assertRaises(ProcessError):
            build_s2(self.item, "ndvi", [51.3, 35.7, 51.30001, 35.70001], self.root / "x.tif")

    def test_dem_merge(self):
        from satgate.process import build_dem
        p = self.root / "dem.tif"
        with rasterio.open(p, "w", driver="GTiff", width=360, height=360, count=1, dtype="float32", crs="EPSG:4326",
                           transform=from_origin(51, 36, 1 / 360, 1 / 360)) as d:
            d.write(np.full((360, 360), 1200, dtype="float32"), 1)
        out = build_dem([{"assets": {"data": {"href": str(p)}}}], BBOX, self.root / "dem_out.tif")
        with rasterio.open(out) as r:
            self.assertEqual(r.dtypes[0], "float32")
            self.assertAlmostEqual(float(r.read(1).mean()), 1200, places=1)

    def test_limits(self):
        from satgate.process import ProcessError, check_limits
        check_limits(BBOX, "ndvi", 100)
        with self.assertRaises(ProcessError):
            check_limits([51, 35, 52, 36], "ndvi", 100)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.scene = make_scene(self.root)
        self.calls = []

        def fetch(url, body=None, timeout=30):
            if "/items/" in url:
                return self.scene
            return {"features": []}
        cfg = Config({"SATGATE_SECRET": SECRET, "SATGATE_PANEL_URL": "https://panel.test", "SATGATE_DATA": str(self.root / "d"),
                      "SATGATE_MAX_KM2": "200", "SATGATE_WORKERS": "1"})
        self.gw = Gateway(cfg, fetch=fetch, post=lambda path, body: self.calls.append((path, json.loads(body))))
        self.gw.notify = lambda job: self.calls.append(("/hooks/satellite/", {k: job[k] for k in ("id", "status")}))
        self.app = make_app(self.gw)

    def tearDown(self):
        self.gw.pool.shutdown(wait=True)
        self.tmp.cleanup()

    def call(self, method, path, body=None, secret=SECRET, headers=None):
        raw = json.dumps(body).encode() if body is not None else b""
        env = {"REQUEST_METHOD": method, "PATH_INFO": path.split("?")[0], "QUERY_STRING": path.partition("?")[2],
               "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
        if secret:
            h = protocol.sign(secret, method, path, raw)
            env["HTTP_X_SAT_TIME"], env["HTTP_X_SAT_SIG"] = h[protocol.H_TIME], h[protocol.H_SIG]
        env.update(headers or {})
        out = {}
        chunks = self.app(env, lambda status, hdr: out.update(status=int(status.split()[0]), headers=dict(hdr)))
        data = b"".join(chunks)
        out["body"] = data
        return out

    def wait(self, jid):
        for _ in range(100):
            j = self.call("GET", f"/v1/jobs/{jid}")
            if json.loads(j["body"])["status"] in ("ready", "failed"):
                return json.loads(j["body"])
            time.sleep(0.1)
        self.fail("timeout")

    def test_health_is_open_but_rest_needs_signature(self):
        self.assertEqual(self.call("GET", "/v1/health", secret=None)["status"], 200)
        self.assertEqual(self.call("GET", "/v1/jobs/" + "a" * 32, secret=None)["status"], 401)
        self.assertEqual(self.call("GET", "/v1/jobs/" + "a" * 32, secret="wrong")["status"], 401)

    def test_401_tells_the_exact_reason(self):
        def reason(**hdr):
            r = self.call("GET", "/v1/jobs/" + "a" * 32, secret=None, headers=hdr)
            self.assertEqual(r["status"], 401)
            return json.loads(r["body"])
        old = protocol.sign(SECRET, "GET", "/v1/jobs/" + "a" * 32, ts=time.time() - 700)
        j = reason(HTTP_X_SAT_TIME=old[protocol.H_TIME], HTTP_X_SAT_SIG=old[protocol.H_SIG], HTTP_X_SAT_KID=old[protocol.H_KID])
        self.assertEqual(j["reason"], "skew")
        self.assertLess(j["skew_s"], -600)
        self.assertIn("ساعت", j["error"])
        bad = protocol.sign("wrong", "GET", "/v1/jobs/" + "a" * 32)
        j = reason(HTTP_X_SAT_TIME=bad[protocol.H_TIME], HTTP_X_SAT_SIG=bad[protocol.H_SIG], HTTP_X_SAT_KID=bad[protocol.H_KID])
        self.assertEqual(j["reason"], "key")
        self.assertIn("یکی نیست", j["error"])
        moved = protocol.sign(SECRET, "GET", "/proxied/v1/jobs/" + "a" * 32)
        j = reason(HTTP_X_SAT_TIME=moved[protocol.H_TIME], HTTP_X_SAT_SIG=moved[protocol.H_SIG], HTTP_X_SAT_KID=moved[protocol.H_KID])
        self.assertEqual(j["reason"], "signature")
        self.assertEqual(reason()["reason"], "missing")

    def test_full_job_flow_with_range_and_delete(self):
        jid = "b" * 32
        r = self.call("POST", "/v1/jobs", {"id": jid, "product": "ndvi", "scene": "S2A_39SUQ_20260601_0_L2A", "bbox": BBOX,
                                           "max_km2": 100})
        self.assertEqual(r["status"], 202)
        job = self.wait(jid)
        self.assertEqual(job["status"], "ready", job)
        self.assertGreater(job["size"], 1000)
        self.assertIn(("/hooks/satellite/", {"id": jid, "status": "ready"}), self.calls)
        # تکرار همان درخواست دوباره کار نمی‌سازد
        self.assertEqual(self.call("POST", "/v1/jobs", {"id": jid, "product": "ndvi", "scene": "x", "bbox": BBOX})["status"], 200)
        full = self.call("GET", f"/v1/jobs/{jid}/file")
        self.assertEqual((full["status"], len(full["body"])), (200, job["size"]))
        self.assertEqual(full["body"][:2], b"II")
        part = self.call("GET", f"/v1/jobs/{jid}/file", headers={"HTTP_RANGE": "bytes=0-99"})
        self.assertEqual((part["status"], len(part["body"])), (206, 100))
        self.assertEqual(self.call("GET", f"/v1/jobs/{jid}/file", headers={"HTTP_RANGE": "bytes=99999999999-"})["status"], 416)
        self.assertEqual(self.call("DELETE", f"/v1/jobs/{jid}")["status"], 200)
        self.assertEqual(self.call("GET", f"/v1/jobs/{jid}")["status"], 404)
        self.assertFalse(self.gw.store.file(jid).exists())

    def test_landsat_job_flow_and_mission_listing(self):
        self.scene = make_landsat(self.root)
        jid = "1" * 32
        r = self.call("POST", "/v1/jobs", {"id": jid, "product": "ndvi", "mission": "landsat", "scene": self.scene["id"],
                                           "bbox": BBOX, "max_km2": 100})
        self.assertEqual(r["status"], 202)
        job = self.wait(jid)
        self.assertEqual(job["status"], "ready", job)
        self.assertEqual(self.gw.store.get(jid)["mission"], "landsat")
        with rasterio.open(self.gw.store.file(jid)) as ds:
            self.assertAlmostEqual(ds.res[0], 30, places=3)
        bad = self.call("POST", "/v1/jobs", {"id": "2" * 32, "product": "ndvi", "mission": "nope", "scene": "s", "bbox": BBOX})
        self.assertEqual(bad["status"], 400)
        # بدون ماموریت = Sentinel-2 (سازگار با پنل قدیمی)
        old = self.call("POST", "/v1/jobs", {"id": "3" * 32, "product": "ndvi", "scene": "S2A_39SUQ_20260601_0_L2A", "bbox": BBOX})
        self.assertEqual(old["status"], 202)
        self.wait("3" * 32)
        self.assertEqual(self.gw.store.get("3" * 32)["mission"], "sentinel2")

    def test_missions_endpoint_reports_each_satellite_and_caches(self):
        n = []

        def fetch(url, body=None, timeout=30):
            n.append(url)
            if "planetarycomputer" in url:
                raise stac.StacError("به کاتالوگ تصویر وصل نشدیم.")
            return {"features": []}
        self.gw.fetch = fetch
        j = json.loads(self.call("GET", "/v1/missions")["body"])["missions"]
        self.assertTrue(j["sentinel2"]["ok"])
        self.assertFalse(j["landsat"]["ok"])
        self.assertIn("وصل نشدیم", j["landsat"]["error"])
        calls = len(n)
        self.call("GET", "/v1/missions")
        self.assertEqual(len(n), calls)               # کش
        self.call("GET", "/v1/missions?refresh=1")
        self.assertGreater(len(n), calls)             # بازخوانی اجباری
        self.assertEqual(self.call("GET", "/v1/missions", secret=None)["status"], 401)

    def test_area_cap_and_bad_input(self):
        base = {"id": "c" * 32, "product": "ndvi", "scene": "s", "bbox": [51.0, 35.0, 51.4, 35.4]}
        r = self.call("POST", "/v1/jobs", base)
        self.assertEqual(r["status"], 422)
        self.assertIn("سقف", json.loads(r["body"])["error"])
        self.assertEqual(self.call("POST", "/v1/jobs", {**base, "id": "zz"})["status"], 400)
        self.assertEqual(self.call("POST", "/v1/jobs", {**base, "product": "nope", "bbox": BBOX})["status"], 400)
        self.assertEqual(self.call("POST", "/v1/jobs", {**base, "scene": "", "bbox": BBOX})["status"], 400)

    def test_failure_is_reported_not_crashed(self):
        del self.scene["assets"]["nir"]
        jid = "d" * 32
        self.call("POST", "/v1/jobs", {"id": jid, "product": "ndvi", "scene": "s", "bbox": BBOX})
        job = self.wait(jid)
        self.assertEqual(job["status"], "failed")
        self.assertIn("باند", job["message"])
        self.assertEqual(self.call("GET", f"/v1/jobs/{jid}/file")["status"], 404)

    def test_install_errors_keep_their_detail_other_errors_do_not(self):
        import satgate.app as app_mod
        for exc, expect_detail in ((ImportError("libexpat.so.1: cannot open shared object file"), True),
                                   (RuntimeError("secret /internal/path"), False)):
            jid = ("f" if expect_detail else "9") * 32
            orig = app_mod.build_scene
            app_mod.build_scene = lambda *a, _e=exc, **k: (_ for _ in ()).throw(_e)
            try:
                self.call("POST", "/v1/jobs", {"id": jid, "product": "ndvi", "scene": "s", "bbox": BBOX})
                job = self.wait(jid)
            finally:
                app_mod.build_scene = orig
            self.assertEqual(job["status"], "failed")
            self.assertIn(exc.__class__.__name__, job["message"])
            self.assertEqual("libexpat" in job["message"], expect_detail)
            self.assertNotIn("/internal/path", job["message"])

    def test_cleanup_removes_old_files(self):
        self.gw.store.put({"id": "e" * 32, "status": "ready"})
        self.assertEqual(self.gw.store.cleanup(24, now=time.time() + 25 * 3600), 1)
        self.assertIsNone(self.gw.store.get("e" * 32))
