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


def make_scene(root: Path, nir_v=3000, red_v=1000, tag="", cloud=None) -> dict:
    """تصویر ساختگی Sentinel-2: چهار باند ۱۰ متری و یک باند ۲۰ متری روی UTM 39N.
    cloud: None، "all"، یا ("north"|"south", عرض جغرافیایی): آن بخش از لایه‌ی SCL کلاس ۹ (ابر) می‌شود، بقیه کلاس ۴."""
    w, s, e, n = transform_bounds("EPSG:4326", "EPSG:32639", 51.2, 35.6, 51.45, 35.85)
    ox, oy = int(w // 10 * 10), int(n // 10 * 10)
    assets = {}
    vals = {"red": red_v, "green": 1200, "blue": 900, "nir": nir_v, "rededge1": 1500, "rededge2": 1700,
            "rededge3": 1800, "nir08": 2900, "swir16": 2000, "swir22": 1600}
    for name, v in vals.items():
        res = 20 if name in ("rededge1", "rededge2", "rededge3", "nir08", "swir16", "swir22") else 10
        size = int((e - w) / res) + 2, int((n - s) / res) + 2
        path = root / f"{tag}{name}.tif"
        with rasterio.open(path, "w", driver="GTiff", width=size[0], height=size[1], count=1, dtype="uint16",
                           crs="EPSG:32639", transform=from_origin(ox, oy, res, res)) as dst:
            dst.write(np.full((size[1], size[0]), v, dtype="uint16"), 1)
        assets[name] = {"href": str(path), "raster:bands": [{"scale": 0.0001, "offset": -0.1}]}
    sz = int((e - w) / 20) + 2, int((n - s) / 20) + 2
    scl = np.full((sz[1], sz[0]), 4, dtype="uint8")
    if cloud == "all":
        scl[:, :] = 9
    elif cloud:
        from rasterio.warp import transform as warp_transform
        row = int((oy - warp_transform("EPSG:4326", "EPSG:32639", [51.32], [cloud[1]])[1][0]) / 20)
        if cloud[0] == "north":
            scl[:row, :] = 9
        else:
            scl[row:, :] = 9
    sp = root / f"{tag}scl.tif"
    with rasterio.open(sp, "w", driver="GTiff", width=sz[0], height=sz[1], count=1, dtype="uint8", crs="EPSG:32639",
                       transform=from_origin(ox, oy, 20, 20)) as dst:
        dst.write(scl, 1)
    assets["scl"] = {"href": str(sp)}
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


class MaskAndCompositeTests(unittest.TestCase):
    """ماسک ابر (SCL و QA_PIXEL) و ترکیب میانه‌ی چند تصویر روی شبکه‌ی مشترک."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bad_pixel_rules(self):
        from satgate.process import ProcessError, bad_pixels
        scl = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], dtype="uint8")
        self.assertEqual(bad_pixels("sentinel2", scl).tolist(),
                         [True, True, False, True, False, False, False, False, True, True, True, False])
        qa = np.array([0, 1, 2, 4, 8, 16, 32, 64, 128, 5440], dtype="uint16")     # بیت ۶ (clear) و ۷ (water) خراب نیست
        self.assertEqual(bad_pixels("landsat", qa).tolist(), [False, True, True, True, True, True, False, False, False, False])
        with self.assertRaises(ProcessError):
            bad_pixels("dem", scl)

    def test_scene_mask_blanks_cloud_and_leaves_rest(self):
        from satgate.process import build_scene
        item = make_scene(self.root, cloud="all")                                    # همه‌ی صحنه ابر
        out = build_scene(item, "sentinel2", "ndvi", BBOX, self.root / "all.tif", mask=True)
        with rasterio.open(out) as r:
            self.assertTrue((r.read(1) == -9999).all())
        item = make_scene(self.root, tag="p_", cloud=("north", 35.715))              # نیمه‌ی شمالی ابر
        out = build_scene(item, "sentinel2", "ndvi", BBOX, self.root / "part.tif", mask=True)
        with rasterio.open(out) as r:
            a = r.read(1)
            bad = (a == -9999)
            self.assertTrue(0.3 < bad.mean() < 0.7)                    # حدود نیمی بی‌اعتبار
            self.assertTrue(bad[: a.shape[0] // 4].all())              # بالا (شمال) ابر
            self.assertFalse(bad[-a.shape[0] // 4:].any())             # پایین (جنوب) صاف
        noscl = make_scene(self.root, tag="n_")
        del noscl["assets"]["scl"]
        from satgate.process import ProcessError
        with self.assertRaises(ProcessError) as cm:
            build_scene(noscl, "sentinel2", "ndvi", BBOX, self.root / "x.tif", mask=True)
        self.assertIn("لایه‌ی کیفیت", str(cm.exception))
        build_scene(noscl, "sentinel2", "ndvi", BBOX, self.root / "ok.tif", mask=False)       # بدون ماسک مشکلی نیست

    def test_utm_grid_snaps_to_resolution(self):
        from satgate.process import utm_grid
        g = utm_grid(BBOX, 10)
        self.assertEqual(g["crs"].to_epsg(), 32639)
        self.assertEqual((g["transform"].a, g["transform"].e), (10, -10))
        self.assertEqual(round(g["transform"].c) % 10, 0)
        self.assertGreater(g["width"], 200)
        self.assertEqual(utm_grid([-60.1, -10.1, -60.0, -10.0], 30)["crs"].to_epsg(), 32720)    # نیمکره‌ی جنوبی

    def test_composite_fills_cloud_with_other_dates(self):
        from satgate.process import build_composite
        # سه تصویر: اولی نیمه‌ی بالایی ابری، دومی نیمه‌ی پایینی ابری، سومی صاف با NIR کمی متفاوت
        # NDVI: a=.333  b=.5  c=.6 (بازتاب NIR/قرمز = .2/.1  .3/.1  .4/.1)
        a = make_scene(self.root, nir_v=3000, red_v=2000, tag="a_", cloud=("north", 35.715))
        b = make_scene(self.root, nir_v=4000, red_v=2000, tag="b_", cloud=("south", 35.715))
        c = make_scene(self.root, nir_v=5000, red_v=2000, tag="c_")
        out, used = build_composite([a, b, c], "sentinel2", "ndvi", BBOX, self.root / "comp.tif")
        self.assertEqual(used, 3)
        with rasterio.open(out) as r:
            arr = r.read(1)
            self.assertTrue((arr != -9999).all())              # هیچ سوراخی نمانده
            self.assertEqual(r.crs.to_epsg(), 32639)
        # بدون ماسک: میانه‌ی ۳ مقدار؛ با ماسک: بالا فقط b و c، پایین فقط a و c
        masked, _ = build_composite([a, b, c], "sentinel2", "ndvi", BBOX, self.root / "m.tif", mask=True)
        unmasked, _ = build_composite([a, b, c], "sentinel2", "ndvi", BBOX, self.root / "u.tif", mask=False)
        with rasterio.open(masked) as m, rasterio.open(unmasked) as u:
            ma, ua = m.read(1), u.read(1)
            self.assertEqual(ma.shape, ua.shape)
            # ترکیب روی باندها انجام می‌شود و بعد شاخص: بدون ماسک NIR میانه‌ی (.2 .3 .4)=.3 و قرمز .1 ← NDVI=.5
            self.assertAlmostEqual(float(np.median(ua)), 0.5, places=3)
            h = ma.shape[0]
            self.assertAlmostEqual(float(ma[h // 8].mean()), 0.5556, places=3)     # شمال: فقط b و c ← NIR=.35 ← (.35-.1)/.45
            self.assertAlmostEqual(float(ma[-h // 8].mean()), 0.5, places=3)       # جنوب: فقط a و c ← NIR=.3

    def test_composite_all_cloudy_gives_nodata_and_unusable_items_skipped(self):
        from satgate.process import ProcessError, build_composite
        cloudy = make_scene(self.root, tag="x_", cloud="all")
        out, used = build_composite([cloudy], "sentinel2", "true_color", BBOX, self.root / "c.tif")
        with rasterio.open(out) as r:
            self.assertTrue((r.read() == 0).all())               # همه ابر: نبود داده (۰)
        bad = make_scene(self.root, tag="y_")
        del bad["assets"]["scl"]
        with self.assertRaises(ProcessError):
            build_composite([bad], "sentinel2", "ndvi", BBOX, self.root / "d.tif")                # هیچ تصویر قابل‌استفاده‌ای نیست
        good = make_scene(self.root, tag="z_")
        _, used = build_composite([bad, good], "sentinel2", "ndvi", BBOX, self.root / "e.tif")
        self.assertEqual(used, 1)                                                                  # تصویر ناقص کنار رفت

    def test_composite_cap_protects_memory(self):
        from satgate import process
        from satgate.process import ProcessError, build_composite
        old = process.MAX_STACK_PX
        process.MAX_STACK_PX = 1000
        try:
            with self.assertRaises(ProcessError):
                build_composite([make_scene(self.root)], "sentinel2", "ndvi", BBOX, self.root / "f.tif")
        finally:
            process.MAX_STACK_PX = old

    def test_landsat_composite_uses_qa_pixel(self):
        from satgate.process import build_composite
        a = make_landsat(self.root)
        sz = rasterio.open(a["assets"]["red"]["href"])
        qa = np.zeros((sz.height, sz.width), dtype="uint16")
        qa[:, : sz.width // 2] = 0b11000        # نیمه‌ی غربی: ابر و سایه
        qp = self.root / "qa.tif"
        with rasterio.open(qp, "w", driver="GTiff", width=sz.width, height=sz.height, count=1, dtype="uint16", crs=sz.crs,
                           transform=sz.transform) as d:
            d.write(qa, 1)
        a["assets"]["qa_pixel"] = {"href": str(qp)}
        out, used = build_composite([a], "landsat", "ndvi", BBOX, self.root / "l.tif")
        self.assertEqual(used, 1)
        with rasterio.open(out) as r:
            arr = r.read(1)
            self.assertTrue((arr == -9999).any() and (arr != -9999).any())


POLY_N = {"type": "Polygon", "coordinates": [[[51.305, 35.720], [51.335, 35.720], [51.335, 35.728], [51.305, 35.728], [51.305, 35.720]]]}
POLY_S = {"type": "Polygon", "coordinates": [[[51.305, 35.702], [51.335, 35.702], [51.335, 35.710], [51.305, 35.710], [51.305, 35.702]]]}
FEATS = [{"id": "plot-A", "geometry": POLY_N}, {"id": "plot-B", "geometry": POLY_S}]


class ZonalModuleTests(unittest.TestCase):
    def test_index_formulas_and_invalid_pixels(self):
        from satgate.zonal import index_array, index_bands
        r = {"nir": np.array([.4, .4, np.nan, .0], "float32"), "red": np.array([.1, .4, .1, .0], "float32"),
             "green": np.array([.2, .2, .2, .2], "float32"), "swir16": np.array([.2, .1, .1, .1], "float32"),
             "swir22": np.array([.1, .1, .1, .1], "float32")}
        nd = index_array(r, "ndvi")
        self.assertAlmostEqual(float(nd[0]), 0.6, places=5)
        self.assertAlmostEqual(float(nd[1]), 0.0, places=5)
        self.assertTrue(np.isnan(nd[2]) and np.isnan(nd[3]))              # بی‌اعتبار و مخرج صفر
        self.assertAlmostEqual(float(index_array(r, "ndwi")[0]), (.2 - .4) / (.2 + .4), places=5)
        self.assertEqual(index_bands("ndmi"), ("nir", "swir16"))
        from satgate.zonal import ZonalError
        with self.assertRaises(ZonalError):
            index_array(r, "nope")

    def test_zonal_stats_per_feature_with_gaps(self):
        from satgate.zonal import zonal_stats
        labels = np.array([[1, 1, 2, 0], [1, 1, 2, 3], [0, 0, 0, 3]], dtype="uint32")
        vals = np.array([[.2, .4, np.nan, 9], [.6, np.nan, np.nan, 1], [5, 5, 5, 3]], dtype="float32")
        st = zonal_stats(labels, vals, 4)
        a = st[0]
        self.assertEqual((a["count"], a["valid"], a["valid_pct"]), (4, 3, 75.0))
        self.assertAlmostEqual(a["mean"], 0.4, places=5)
        self.assertAlmostEqual(a["median"], 0.4, places=5)
        self.assertEqual((round(a["min"], 3), round(a["max"], 3)), (0.2, 0.6))
        self.assertGreater(a["std"], 0)
        self.assertEqual(st[1]["valid"], 0)                                # همه ابر: فقط شمارش، بدون میانگین
        self.assertNotIn("mean", st[1])
        self.assertEqual((st[2]["count"], st[2]["mean"]), (2, 2.0))
        self.assertIsNone(st[3])                                           # عارضه‌ای که روی شبکه نیست

    def test_bbox_and_labels(self):
        from satgate.process import utm_grid
        from satgate.zonal import bbox_of, feature_labels
        bb = bbox_of(FEATS)
        self.assertEqual([round(v, 3) for v in bb], [51.305, 35.702, 51.335, 35.728])
        g = utm_grid(BBOX, 10)
        lab = feature_labels(FEATS, (g["height"], g["width"]), g["transform"], g["crs"])
        self.assertEqual(set(np.unique(lab).tolist()), {0, 1, 2})
        self.assertGreater(int((lab == 1).sum()), 1000)
        self.assertGreater(int((lab == 2).sum()), 1000)


class ZonalJobTests(unittest.TestCase):
    """سری زمانی روی دروازه: سه تصویر، یکی با ابر روی نیمه‌ی شمالی؛ آمار هر قطعه جدا و درصد معتبر درست."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        full = {"type": "Polygon", "coordinates": [[[51.0, 35.4], [51.7, 35.4], [51.7, 36.1], [51.0, 36.1], [51.0, 35.4]]]}
        self.scenes = {}
        for k, (nir, cloud, cc) in enumerate([(3000, None, 5), (4000, ("north", 35.715), 12), (5000, None, 8)]):
            it = make_scene(self.root, nir_v=nir, red_v=2000, tag=f"z{k}_", cloud=cloud)
            it["id"] = f"S2A_39SUQ_2026060{k + 1}_0_L2A"
            it["properties"].update(datetime=f"2026-06-0{k + 1}T07:00:00Z", **{"eo:cloud_cover": cc})
            self.scenes[it["id"]] = it
        self.full = full

        def fetch(url, body=None, timeout=30):
            if "/items/" in url:
                return self.scenes[url.rsplit("/", 1)[1]]
            return {"features": [{"id": i, "collection": "sentinel-2-l2a", "geometry": full,
                                  "properties": {"datetime": it["properties"]["datetime"],
                                                 "eo:cloud_cover": it["properties"]["eo:cloud_cover"]}}
                                 for i, it in self.scenes.items()]}
        self.fetch = fetch

    def tearDown(self):
        self.tmp.cleanup()

    def params(self, **kw):
        from satgate import analysis
        body = {"features": FEATS, "index": "ndvi", "mission": "sentinel2", "start": "2026-06-01", "end": "2026-06-30",
                "max_cloud": 50, "max_scenes": 5, "mask": True, **kw}
        p, err = analysis.validate(body, 500)
        self.assertEqual(err, "", err)
        return p

    def test_time_series_with_cloud_gaps(self):
        from satgate import analysis
        res = analysis.run_zonal(self.params(), self.fetch)
        self.assertEqual([s["date"] for s in res["scenes"]], ["2026-06-01", "2026-06-02", "2026-06-03"])   # به ترتیب تاریخ
        by = {(r["feature"], r["date"]): r for r in res["rows"]}
        # NDVI: روز۱ NIR .2 قرمز .1 ← .3333 ؛ روز۲ NIR .3 ← .5 ؛ روز۳ NIR .4 ← .6
        self.assertAlmostEqual(by[("plot-B", "2026-06-01")]["mean"], 0.3333, places=3)
        self.assertAlmostEqual(by[("plot-B", "2026-06-02")]["mean"], 0.5, places=3)
        self.assertAlmostEqual(by[("plot-B", "2026-06-03")]["mean"], 0.6, places=3)
        self.assertEqual(by[("plot-B", "2026-06-02")]["valid_pct"], 100.0)
        a2 = by[("plot-A", "2026-06-02")]                                    # شمال در روز ۲ ابری
        self.assertEqual((a2["valid"], a2["valid_pct"]), (0, 0.0))
        self.assertNotIn("mean", a2)
        self.assertAlmostEqual(by[("plot-A", "2026-06-03")]["mean"], 0.6, places=3)
        self.assertEqual(res["features"], 2)
        self.assertEqual(res["skipped"], [])

    def test_mask_off_ignores_clouds(self):
        from satgate import analysis
        res = analysis.run_zonal(self.params(mask=False), self.fetch)
        by = {(r["feature"], r["date"]): r for r in res["rows"]}
        self.assertEqual(by[("plot-A", "2026-06-02")]["valid_pct"], 100.0)
        self.assertAlmostEqual(by[("plot-A", "2026-06-02")]["mean"], 0.5, places=3)

    def test_other_indices_use_other_bands(self):
        from satgate import analysis
        res = analysis.run_zonal(self.params(index="ndwi", max_scenes=1), self.fetch)
        row = res["rows"][0]
        # NDWI=(green-nir)/(green+nir): سبز DN 1200 ← .02 ، NIR کمتر ← منفی (خشکی)
        self.assertLess(row["mean"], 0)

    def test_skips_broken_scene_but_keeps_others(self):
        from satgate import analysis
        first = next(iter(self.scenes.values()))
        del first["assets"]["nir"]
        res = analysis.run_zonal(self.params(), self.fetch)
        self.assertEqual(len(res["scenes"]), 2)
        self.assertEqual(len(res["skipped"]), 1)
        self.assertIn("nir", res["skipped"][0]["reason"])

    def test_validation_rules(self):
        from satgate import analysis
        ok = {"features": FEATS, "index": "ndvi", "start": "2026-06-01", "end": "2026-06-30"}
        self.assertEqual(analysis.validate(ok, 500)[1], "")
        bad = [({**ok, "index": "nope"}, "شاخص"), ({**ok, "mission": "nope"}, "ماهواره"), ({**ok, "features": []}, "عارضه"),
               ({**ok, "features": [{"id": 1, "geometry": {"type": "Point", "coordinates": [51, 35]}}]}, "چندضلعی"),
               ({**ok, "features": [{"geometry": POLY_N}]}, "چندضلعی"), ({**ok, "start": "2026-07-01"}, "بازه"),
               ({**ok, "start": "2024-01-01"}, "بازه"), ({**ok, "features": FEATS * 600}, "حداکثر")]
        for body, word in bad:
            self.assertIn(word, analysis.validate(body, 500)[1], body.get("index"))
        self.assertIn("سقف", analysis.validate(ok, 1)[1])                    # محدوده‌ی عارضه‌ها از سقف پلن بزرگ‌تر
        self.assertEqual(analysis.validate({**ok, "max_scenes": 999}, 500)[0]["max_scenes"], 24)

    def test_no_scenes_message(self):
        from satgate import analysis
        from satgate.process import ProcessError
        with self.assertRaises(ProcessError) as cm:
            analysis.run_zonal(self.params(), lambda *a, **k: {"features": []})
        self.assertIn("تصویری با این شرایط", str(cm.exception))


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
        names = {a for m in spec.MISSIONS.values() for s_ in m.sources for a in (*s_.assets.values(), s_.mask_asset, s_.asset) if a}
        feature = {"id": "X", "assets": {a: {"href": "https://x.example/" + a} for a in names}}

        def fetch(url, body=None, timeout=30):
            n.append(url)
            if "planetarycomputer" in url:
                raise stac.StacError("به کاتالوگ تصویر وصل نشدیم.")
            return {"features": [feature]}
        self.gw.fetch = fetch
        from unittest import mock
        patcher = mock.patch.object(stac, "_read_head", lambda href: b"x")
        patcher.start()
        self.addCleanup(patcher.stop)
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

    def test_masked_scene_and_composite_jobs_via_api(self):
        full = {"type": "Polygon", "coordinates": [[[51.0, 35.4], [51.7, 35.4], [51.7, 36.1], [51.0, 36.1], [51.0, 35.4]]]}
        scenes = {}
        for k, (nir, cloud) in enumerate([(3000, ("north", 35.715)), (4000, ("south", 35.715)), (5000, None)]):
            it = make_scene(self.root, nir_v=nir, red_v=2000, tag=f"j{k}_", cloud=cloud)
            it["id"] = f"S2A_39SUQ_2026060{k + 1}_0_L2A"
            it["properties"]["eo:cloud_cover"] = 10 * (k + 1)
            scenes[it["id"]] = it

        def fetch(url, body=None, timeout=30):
            if "/items/" in url:
                return scenes[url.rsplit("/", 1)[1]]
            return {"features": [{"id": i, "collection": "sentinel-2-l2a", "geometry": full,
                                  "properties": {"datetime": it["properties"]["datetime"], "eo:cloud_cover": it["properties"]["eo:cloud_cover"]}}
                                 for i, it in scenes.items()]}
        self.gw.fetch = fetch
        ids = list(scenes)
        # تصویر تکی با ماسک
        r = self.call("POST", "/v1/jobs", {"id": "4" * 32, "product": "ndvi", "scene": ids[0], "bbox": BBOX, "mask": True})
        self.assertEqual(r["status"], 202)
        self.assertEqual(self.wait("4" * 32)["status"], "ready")
        with rasterio.open(self.gw.store.file("4" * 32)) as ds:
            a = ds.read(1)
            self.assertTrue((a == -9999).any())                      # نیمه‌ی ابری ماسک شد
        # ترکیب: دروازه خودش تصویرها را پیدا می‌کند
        comp = {"start": "2026-06-01", "end": "2026-06-30", "max_cloud": 50, "max_scenes": 3}
        r = self.call("POST", "/v1/jobs", {"id": "5" * 32, "product": "ndvi", "bbox": BBOX, "mask": True, "composite": comp})
        self.assertEqual(r["status"], 202, r["body"])
        job = self.wait("5" * 32)
        self.assertEqual((job["status"], job["used"], job["of"]), ("ready", 3, 3), job)
        with rasterio.open(self.gw.store.file("5" * 32)) as ds:
            self.assertTrue((ds.read(1) != -9999).all())            # ابرها با تصویرهای دیگر پر شد
        stored = self.gw.store.get("5" * 32)
        self.assertEqual(stored["composite"]["max_scenes"], 3)

    def test_analyze_job_via_api_returns_small_result_and_forgets_polygons(self):
        z = ZonalJobTests("test_time_series_with_cloud_gaps")
        z.setUp()
        try:
            self.gw.fetch = z.fetch
            body = {"id": "a" * 32, "features": FEATS, "index": "ndvi", "mission": "sentinel2", "start": "2026-06-01",
                    "end": "2026-06-30", "max_cloud": 50, "max_scenes": 5, "mask": True, "max_km2": 100}
            r = self.call("POST", "/v1/analyze", body)
            self.assertEqual(r["status"], 202, r["body"])
            job = self.wait("a" * 32)
            self.assertEqual((job["status"], job["used"], job["of"]), ("ready", 3, 3), job)
            self.assertEqual(job["rows"], 6)
            self.assertIn(("/hooks/satellite/", {"id": "a" * 32, "status": "ready"}), self.calls)
            res = self.call("GET", f"/v1/jobs/{'a' * 32}/result")
            self.assertEqual(res["status"], 200)
            data = json.loads(res["body"])
            self.assertEqual(len(data["rows"]), 6)
            self.assertLess(len(res["body"]), 5000)
            self.assertIsNone(self.gw.store.get("a" * 32).get("params"))          # چندضلعی‌های کاربر روی دروازه نمی‌ماند
            self.assertEqual(self.call("POST", "/v1/analyze", body)["status"], 200)  # تکراری
            self.call("DELETE", f"/v1/jobs/{'a' * 32}")
            self.assertFalse(self.gw.store.result("a" * 32).exists())
        finally:
            z.tearDown()

    def test_analyze_rejects_bad_input_and_unsigned(self):
        r = self.call("POST", "/v1/analyze", {"id": "b" * 32, "features": [], "index": "ndvi"})
        self.assertEqual(r["status"], 422)
        self.assertEqual(self.call("POST", "/v1/analyze", {"id": "zz"})["status"], 400)
        self.assertEqual(self.call("POST", "/v1/analyze", {"id": "c" * 32}, secret=None)["status"], 401)
        self.assertEqual(self.call("GET", "/v1/jobs/" + "d" * 32 + "/result")["status"], 404)

    def test_composite_params_are_validated(self):
        base = {"id": "6" * 32, "product": "ndvi", "bbox": BBOX}
        for bad in ({"start": "x", "end": "2026-01-01"}, {"start": "2026-02-01", "end": "2026-01-01"},
                    {"start": "2024-01-01", "end": "2026-01-01"}, {"start": "2026-01-01", "end": "2026-02-01", "max_scenes": "n"}):
            self.assertEqual(self.call("POST", "/v1/jobs", {**base, "composite": bad})["status"], 400, bad)
        dem = self.call("POST", "/v1/jobs", {"id": "7" * 32, "product": "dem", "bbox": BBOX,
                                             "composite": {"start": "2026-01-01", "end": "2026-02-01"}})
        self.assertEqual(dem["status"], 400)
        ok = self.call("POST", "/v1/jobs", {**base, "id": "8" * 32, "composite": {"start": "2026-06-01", "end": "2026-06-30",
                                                                               "max_scenes": 99, "max_cloud": 500}})
        self.assertEqual(ok["status"], 202)
        j = self.gw.store.get("8" * 32)["composite"]
        self.assertEqual((j["max_scenes"], j["max_cloud"]), (10, 100.0))              # به سقف می‌رسد

    def test_composite_with_no_scenes_fails_clearly(self):
        self.gw.fetch = lambda url, body=None, timeout=30: {"features": []}
        self.call("POST", "/v1/jobs", {"id": "9" * 32, "product": "ndvi", "bbox": BBOX,
                                       "composite": {"start": "2026-06-01", "end": "2026-06-30"}})
        job = self.wait("9" * 32)
        self.assertEqual(job["status"], "failed")
        self.assertIn("تصویری با این شرایط", job["message"])

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
