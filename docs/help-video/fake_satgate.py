"""دروازه‌ی ماهواره‌ی ساختگی برای ضبط ویدیوی راهنما (بدون اینترنت): همان کد واقعی دروازه (satgate) با کاتالوگ و تصویرهای
ساختگی؛ تصویرها روی همان قطعه‌های نمایشی (satdemo.py) و با سری زمانی NDVI ساخته می‌شوند.
python docs/help-video/fake_satgate.py [پورت]   ← همان‌جا که demo.py serve را اجرا کرده‌اید نیازی نیست؛ serve خودش آن را بالا می‌آورد."""
import sys
import tempfile
import threading
from datetime import date
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
import satdemo as D  # noqa: E402
from rasterio.features import rasterize  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from rasterio.warp import transform_bounds, transform_geom  # noqa: E402

from satgate.app import Config, Gateway, make_app  # noqa: E402

SECRET = "demo-secret"
RED, SCALE, OFFSET = 0.08, 0.0001, -0.1


def build_scene(root: Path, t: int) -> dict:
    w, s, e, n = transform_bounds("EPSG:4326", "EPSG:32639", *D.SCENE_BBOX)
    ox, oy = int(w // 20 * 20), int(n // 20 * 20)
    polys = []
    for i, (_, _, ring) in enumerate(D.parcels()):
        g = transform_geom("EPSG:4326", "EPSG:32639", {"type": "Polygon", "coordinates": [ring]})
        polys.append((g, i + 1))
    rng = np.random.default_rng(100 + t)
    assets, tag = {}, f"s{t}_"

    def layer(res: int):
        size = int((e - w) / res) + 2, int((n - s) / res) + 2
        tr = from_origin(ox, oy, res, res)
        lab = rasterize(polys, out_shape=(size[1], size[0]), transform=tr, fill=0, dtype="int32")
        v = np.full(lab.shape, 0.12)
        for k in range(12):
            v = np.where(lab == k + 1, D.ndvi(k, t), v)
        v = np.clip(v + rng.normal(0, 0.03, v.shape), 0.02, 0.92)
        return size, tr, v

    for res, names in ((10, ("red", "green", "blue", "nir")), (20, ("rededge1", "rededge2", "rededge3", "nir08", "swir16", "swir22"))):
        size, tr, v = layer(res)
        nir = RED * (1 + v) / (1 - v)
        refl = {"red": np.full(v.shape, RED), "green": 0.10 + 0.06 * v, "blue": np.full(v.shape, 0.06) + 0.01 * v, "nir": nir,
                "nir08": nir * 0.97, "rededge1": RED + (nir - RED) * 0.3, "rededge2": RED + (nir - RED) * 0.55,
                "rededge3": RED + (nir - RED) * 0.8, "swir16": 0.25 - 0.18 * v, "swir22": 0.18 - 0.12 * v}
        for name in names:
            dn = np.clip((refl[name] - OFFSET) / SCALE, 1, 65000).astype("uint16")
            path = root / f"{tag}{name}.tif"
            with rasterio.open(path, "w", driver="GTiff", width=size[0], height=size[1], count=1, dtype="uint16",
                               crs="EPSG:32639", transform=tr) as dst:
                dst.write(dn, 1)
            assets[name] = {"href": str(path), "raster:bands": [{"scale": SCALE, "offset": OFFSET}]}
    size, tr, _ = layer(20)
    sp = root / f"{tag}scl.tif"
    with rasterio.open(sp, "w", driver="GTiff", width=size[0], height=size[1], count=1, dtype="uint8", crs="EPSG:32639", transform=tr) as dst:
        dst.write(np.full((size[1], size[0]), 4, dtype="uint8"), 1)
    assets["scl"] = {"href": str(sp)}
    day = D.DATES[t]
    b = D.SCENE_BBOX
    geom = {"type": "Polygon", "coordinates": [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]]}
    return {"id": f"S2B_39SUQ_{day.replace('-', '')}_0_L2A", "collection": "sentinel-2-l2a", "assets": assets, "geometry": geom,
            "properties": {"datetime": day + "T07:05:00Z", "eo:cloud_cover": D.CLOUD[t], "platform": "sentinel-2b", "grid:code": "MGRS-39SUQ"}}


def make(port: int = 8099, panel: str = "http://localhost:8765"):
    root = Path(tempfile.mkdtemp(prefix="fake-satgate-"))
    items = [build_scene(root, t) for t in range(len(D.DATES))]

    def fetch(url, body=None, timeout=30):
        if "/items/" in url:
            return next(i for i in items if i["id"] == url.rsplit("/", 1)[1])
        if body is None or body.get("collections") != ["sentinel-2-l2a"]:
            return {"features": []}                                  # Landsat و بقیه: در دسترس نیست
        start, end = (x[:10] for x in body["datetime"].split("/"))
        cl = body.get("query", {}).get("eo:cloud_cover", {}).get("lte", 100)
        return {"features": [{k: v for k, v in i.items() if k != "assets"} | {"assets": {}} for i in items
                             if start <= i["properties"]["datetime"][:10] <= end and i["properties"]["eo:cloud_cover"] <= cl]}

    cfg = Config({"SATGATE_SECRET": SECRET, "SATGATE_PANEL_URL": panel, "SATGATE_DATA": str(root / "data"), "SATGATE_WORKERS": "2"})
    gw = Gateway(cfg, fetch=fetch)

    class S(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    class Quiet(WSGIRequestHandler):
        def log_message(self, *a):
            pass

    return make_server("127.0.0.1", port, make_app(gw), server_class=S, handler_class=Quiet)


def start(port: int = 8099, panel: str = "http://localhost:8765"):
    srv = make(port, panel)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print("fake satgate on", p, date.today(), flush=True)
    make(p).serve_forever()
