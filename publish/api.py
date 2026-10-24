"""
آدرس‌های عمومی: کاشی برداری، TileJSON و OGC API - Features (Part 1: Core، GeoJSON).

/tiles/<layer>/{z}/{x}/{y}.mvt      کاشی برداری (Mapbox Vector Tile)
/tiles/<layer>.json                  TileJSON برای MapLibre و QGIS
/ogc/<service>/                      صفحه آغاز OGC API
/ogc/<service>/conformance
/ogc/<service>/collections[/<id>[/items[/<fid>]]]
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urlencode

from django.core.cache import cache
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from . import access, engine
from .models import Layer, Service

log = logging.getLogger(__name__)
TILE_TTL = 60
CONFORMANCE = [
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30",
]
CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"


def _cors(resp, public=True):
    resp["Access-Control-Allow-Origin"] = "*"
    resp["Access-Control-Allow-Headers"] = "Authorization, X-API-Key, Content-Type"
    resp["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp["Vary"] = "Authorization, X-API-Key"
    if "Cache-Control" not in resp:
        resp["Cache-Control"] = f"public, max-age={TILE_TTL}" if public else "private, max-age=0, no-store"
    return resp


def _error(exc: access.Denied | Exception, status: int = 400, code: str = "BadRequest"):
    if isinstance(exc, access.Denied):
        status, code, msg = exc.status, exc.code, exc.message
    else:
        msg = str(exc)
    resp = JsonResponse({"code": code, "description": msg}, status=status, json_dumps_params={"ensure_ascii": False})
    resp["Cache-Control"] = "no-store"
    return _cors(resp)


def _options():
    return _cors(HttpResponse(status=204))


def _json(data, public=True, content_type="application/json"):
    resp = HttpResponse(json.dumps(data, ensure_ascii=False), content_type=f"{content_type}; charset=utf-8")
    return _cors(resp, public)


def _key_qs(request) -> str:
    """کلید را در لینک‌های بعدی (TileJSON، صفحه‌بندی) نگه می‌دارد اگر با ?key آمده باشد."""
    key = request.GET.get("key")
    return f"?{urlencode({'key': key})}" if key else ""


# ---------------------------------------------------------------------- کاشی‌ها
@require_http_methods(["GET", "HEAD", "OPTIONS"])
def tile(request, slug, z, x, y):
    if request.method == "OPTIONS":
        return _options()
    layer = Layer.objects.select_related("service__database__plan").filter(slug=slug).first()
    if layer is None:
        return _error(Exception("لایه پیدا نشد."), 404, "NotFound")
    try:
        owner = access.check_layer(request, layer)
        if not owner:
            access.count(layer.service.database)
    except access.Denied as exc:
        return _error(exc)
    if not (z <= 24 and x < 2 ** z and y < 2 ** z):
        return _error(Exception("مختصات کاشی نامعتبر است."), 400, "InvalidParameterValue")
    if not (layer.min_zoom <= z <= layer.max_zoom):
        data = b""
    else:
        ck = f"tile2:{layer.pk}:{int(layer.updated_at.timestamp())}:{z}/{x}/{y}"
        data = cache.get(ck)
        if data is None:
            try:
                data = engine.tile(layer, z, x, y)
            except engine.EngineError as exc:
                log.warning("tile %s %s/%s/%s: %s", slug, z, x, y, exc)
                return _error(exc, 500, "TileError")
            except Exception as exc:  # noqa: BLE001  (مثلاً اتصال به سرور پایگاه داده)
                log.exception("tile failed")
                return _error(Exception(f"ساخت کاشی ممکن نشد: {exc}"), 503, "Unavailable")
            cache.set(ck, data, TILE_TTL)
    resp = HttpResponse(data, content_type="application/vnd.mapbox-vector-tile")
    return _cors(resp, layer.is_public)


@require_http_methods(["GET", "OPTIONS"])
def tilejson(request, slug):
    if request.method == "OPTIONS":
        return _options()
    layer = Layer.objects.select_related("service__database__plan").filter(slug=slug).first()
    if layer is None:
        return _error(Exception("لایه پیدا نشد."), 404, "NotFound")
    try:
        access.check_layer(request, layer)
    except access.Denied as exc:
        return _error(exc)
    base = request.build_absolute_uri(f"/tiles/{layer.slug}/")
    fields = {c: "" for c in (layer.columns or [])}
    if not fields:
        try:
            meta = engine.describe(layer)
            fields = {n: t for n, t in meta["columns"] if n != layer.geom_column}
        except engine.EngineError:
            fields = {}
    data = {
        "tilejson": "3.0.0", "name": layer.display_title, "description": layer.description,
        "attribution": "postgis.ir", "scheme": "xyz", "format": "pbf",
        "tiles": [base + "{z}/{x}/{y}.mvt" + _key_qs(request)],
        "minzoom": layer.min_zoom, "maxzoom": min(layer.max_zoom, 22),
        "vector_layers": [{"id": layer.collection_id, "fields": {k: str(v) for k, v in fields.items()}}],
    }
    if layer.bbox:
        data["bounds"] = layer.bbox
        data["center"] = [(layer.bbox[0] + layer.bbox[2]) / 2, (layer.bbox[1] + layer.bbox[3]) / 2, 10]
    return _json(data, layer.is_public)


# ---------------------------------------------------------------------- OGC API - Features
def _service(slug) -> Service:
    return get_object_or_404(Service.objects.select_related("database__plan"), slug=slug)


def _visible_layers(request, service):
    qs = service.layers.all()
    return qs if access.full_access(request, service.database) else qs.filter(is_public=True)


def _abs(request, path: str, **params) -> str:
    q = {k: v for k, v in params.items() if v not in (None, "")}
    if request.GET.get("key"):
        q["key"] = request.GET["key"]
    return request.build_absolute_uri(path) + (f"?{urlencode(q)}" if q else "")


def _collection_doc(request, service, layer) -> dict:
    root = f"/ogc/{service.slug}/collections/{layer.collection_id}"
    doc = {
        "id": layer.collection_id, "title": layer.display_title, "description": layer.description,
        "itemType": "feature", "crs": [CRS84], "storageCrs": f"http://www.opengis.net/def/crs/EPSG/0/{layer.srid}",
        "links": [
            {"href": _abs(request, root), "rel": "self", "type": "application/json", "title": "این مجموعه"},
            {"href": _abs(request, root + "/items"), "rel": "items", "type": "application/geo+json",
             "title": "عوارض"},
            {"href": _abs(request, f"/tiles/{layer.slug}.json"), "rel": "tiles", "type": "application/json",
             "title": "TileJSON کاشی برداری"},
        ],
    }
    if layer.bbox:
        doc["extent"] = {"spatial": {"bbox": [layer.bbox], "crs": CRS84}}
    return doc


def _find_layer(request, service, cid) -> Layer:
    for layer in _visible_layers(request, service):
        if layer.collection_id == cid:
            return layer
    raise Http404


def _ogc(handler):
    """قالب مشترک: OPTIONS، بررسی پایگاه داده، شمارش مصرف، خطاها به JSON."""
    @require_http_methods(["GET", "HEAD", "OPTIONS"])
    def view(request, slug, *args, **kwargs):
        if request.method == "OPTIONS":
            return _options()
        service = Service.objects.select_related("database__plan").filter(slug=slug).first()
        if service is None:
            return _error(Exception("سرویس پیدا نشد."), 404, "NotFound")
        try:
            access.check_database(service.database)
            if not access.is_owner(request, service.database):
                access.count(service.database)
            return handler(request, service, *args, **kwargs)
        except access.Denied as exc:
            return _error(exc)
        except Http404:
            return _error(Exception("پیدا نشد."), 404, "NotFound")
        except (engine.EngineError, ValueError) as exc:
            return _error(exc, 400, "InvalidParameterValue")
    return view


@_ogc
def landing(request, service):
    base = f"/ogc/{service.slug}"
    title = service.title or f"postgis.ir · {service.slug}"
    return _json({
        "title": title, "description": "OGC API - Features از postgis.ir",
        "links": [
            {"href": _abs(request, base + "/"), "rel": "self", "type": "application/json", "title": "این سند"},
            {"href": _abs(request, base + "/conformance"), "rel": "conformance", "type": "application/json"},
            {"href": _abs(request, base + "/collections"), "rel": "data", "type": "application/json"},
        ]})


@_ogc
def conformance(request, service):
    return _json({"conformsTo": CONFORMANCE})


@_ogc
def collections(request, service):
    layers = list(_visible_layers(request, service))
    return _json({
        "links": [{"href": _abs(request, f"/ogc/{service.slug}/collections"), "rel": "self",
                   "type": "application/json"}],
        "collections": [_collection_doc(request, service, x) for x in layers]},
        public=all(x.is_public for x in layers))


@_ogc
def collection(request, service, cid):
    layer = _find_layer(request, service, cid)
    return _json(_collection_doc(request, service, layer), layer.is_public)


def _parse_bbox(value: str):
    if not value:
        return None
    parts = [float(v) for v in value.split(",")]
    if len(parts) == 6:
        parts = [parts[0], parts[1], parts[3], parts[4]]
    if len(parts) != 4:
        raise ValueError("bbox باید چهار عدد باشد: minLon,minLat,maxLon,maxLat")
    return parts


RESERVED = {"bbox", "limit", "offset", "f", "key", "datetime", "crs", "bbox-crs", "properties"}


@_ogc
def items(request, service, cid):
    layer = _find_layer(request, service, cid)
    limit = int(request.GET.get("limit", 100))
    offset = int(request.GET.get("offset", 0))
    bbox = _parse_bbox(request.GET.get("bbox", ""))
    filters = {k: v for k, v in request.GET.items() if k not in RESERVED}
    fc = engine.features(layer, bbox=bbox, limit=limit, offset=offset, filters=filters)
    path = f"/ogc/{service.slug}/collections/{cid}/items"
    keep = {k: v for k, v in request.GET.items() if k not in ("offset", "key")}
    fc["links"] = [{"href": _abs(request, path, **keep, offset=offset or None), "rel": "self",
                    "type": "application/geo+json"}]
    if fc["numberReturned"] >= min(max(limit, 1), engine.MAX_ITEMS):
        fc["links"].append({"href": _abs(request, path, **keep, offset=offset + fc["numberReturned"]),
                            "rel": "next", "type": "application/geo+json"})
    return _json(fc, layer.is_public, content_type="application/geo+json")


@_ogc
def item(request, service, cid, fid):
    layer = _find_layer(request, service, cid)
    fc = engine.features(layer, fid=fid, limit=1)
    if not fc["features"]:
        raise Http404
    feat = fc["features"][0]
    feat["links"] = [{"href": _abs(request, f"/ogc/{service.slug}/collections/{cid}/items/{fid}"), "rel": "self",
                      "type": "application/geo+json"},
                     {"href": _abs(request, f"/ogc/{service.slug}/collections/{cid}"), "rel": "collection",
                      "type": "application/json"}]
    return _json(feat, layer.is_public, content_type="application/geo+json")
