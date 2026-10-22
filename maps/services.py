"""ساخت نقشه چندلایه و افزودن جدول‌ها به آن؛ سهمیه‌های پلن هم همین‌جا بررسی می‌شوند."""
from __future__ import annotations

from django.db import transaction
from django.db.models import F

from databases.explorer import Explorer, ExplorerError
from publish import engine
from publish.styles import CATEGORY_COLORS, STYLE_DEFAULT

from .models import MapLayer, WebMap

QUICK_MAX = 10  # «نمایش با هم» بدون ذخیره


class MapError(Exception):
    pass


def spatial_tables(db) -> list[dict]:
    """جدول‌هایی که می‌شود روی نقشه آورد: ستون geometry با SRID معلوم."""
    out = []
    for t in Explorer(db).tables():
        geoms = [g for g in t.geometry if not g["geography"] and g["srid"]]
        if geoms:
            g = geoms[0]
            out.append({"schema": t.schema, "table": t.name, "geom_column": g["column"], "srid": g["srid"],
                        "geom_type": g["type"], "rows": t.rows_estimate, "key": f"{t.schema}.{t.name}"})
    return out


def parse_key(value: str) -> tuple[str, str]:
    schema, _, table = (value or "").partition(".")
    if not table:
        return "public", schema
    return schema, table


def find_table(db, schema: str, table: str) -> dict:
    for t in spatial_tables(db):
        if t["schema"] == schema and t["table"] == table:
            return t
    raise MapError(f"جدول مکانی «{table}» پیدا نشد یا سیستم مختصات آن مشخص نیست (SRID 0).")


def default_style(index: int) -> dict:
    """رنگ هر لایه تازه با لایه‌های قبلی فرق دارد تا کنار هم تشخیص داده شوند."""
    style = {k: v for k, v in STYLE_DEFAULT.items() if k != "basemap"}
    style["color"] = CATEGORY_COLORS[index % len(CATEGORY_COLORS)]
    return style


def layer_style(layer) -> dict:
    return {**default_style(0), **{k: v for k, v in (layer.style or {}).items() if k != "basemap"}}


def all_fields(layer) -> list[tuple[str, str]]:
    """همه ستون‌های غیرهندسی جدول (نه فقط آن‌هایی که در کاشی می‌آیند)."""
    meta = engine.describe(layer)
    return [(n, t) for n, t in meta["columns"]
            if n != layer.geom_column and t not in ("geometry", "geography", "raster", "bytea")]


def _check_map_quota(db):
    cap = db.plan.maps
    if WebMap.objects.filter(database=db).count() >= cap:
        raise MapError(f"پلن شما حداکثر {cap} نقشه چندلایه دارد. یک نقشه را حذف کنید یا پلن را ارتقا دهید.")


def add_layer(webmap: WebMap, schema: str, table: str, info: dict | None = None) -> MapLayer:
    db = webmap.database
    if webmap.layers.filter(schema=schema, table=table).exists():
        raise MapError(f"جدول «{table}» از قبل در این نقشه هست.")
    count = webmap.layers.count()
    if count >= db.plan.map_layers:
        raise MapError(f"پلن شما حداکثر {db.plan.map_layers} لایه در هر نقشه دارد.")
    t = info or find_table(db, schema, table)
    # لایه تازه بالای بقیه قرار می‌گیرد
    webmap.layers.update(position=F("position") + 1)
    layer = MapLayer(webmap=webmap, schema=t["schema"], table=t["table"], geom_column=t["geom_column"],
                     srid=t["srid"], geom_type=t["geom_type"], position=0, style=default_style(count))
    try:
        layer.bbox = engine.extent(layer)
    except (engine.EngineError, ExplorerError):
        layer.bbox = []
    layer.save()
    WebMap.objects.filter(pk=webmap.pk).update(updated_at=layer.updated_at)
    return layer


def create_map(db, user, title: str, keys: list[str] | None = None, description: str = "") -> WebMap:
    """نقشه تازه، و اگر جدول‌هایی انتخاب شده باشند همه با هم اضافه می‌شوند (اولی بالاترین)."""
    _check_map_quota(db)
    keys = list(dict.fromkeys(k for k in (keys or []) if k))
    if len(keys) > db.plan.map_layers:
        raise MapError(f"پلن شما حداکثر {db.plan.map_layers} لایه در هر نقشه دارد؛ کمتر انتخاب کنید.")
    tables = {t["key"]: t for t in spatial_tables(db)} if keys else {}
    missing = [k for k in keys if k not in tables]
    if missing:
        raise MapError(f"جدول مکانی «{missing[0]}» پیدا نشد.")
    from iranmap import basemap

    with transaction.atomic():
        webmap = WebMap.objects.create(database=db, created_by=user, title=(title or "نقشه بی‌نام")[:120],
                                       description=description[:1000],
                                       basemap="iran" if basemap.available() else "osm")
        for k in reversed(keys):
            t = tables[k]
            add_layer(webmap, t["schema"], t["table"], t)
    return webmap


def duplicate(webmap: WebMap, user) -> WebMap:
    db = webmap.database
    _check_map_quota(db)
    with transaction.atomic():
        copy = WebMap.objects.create(database=db, created_by=user, title=f"{webmap.title} (کپی)"[:120],
                                     description=webmap.description, basemap=webmap.basemap, view=webmap.view)
        for layer in webmap.layers.all():
            layer.pk = None
            layer.webmap = copy
            layer.save()
    return copy


def quick_layers(db, keys: list[str]) -> list[MapLayer]:
    """لایه‌های ذخیره‌نشده برای «نمایش با هم»: همان ترتیب انتخاب، رنگ جدا برای هر کدام."""
    keys = list(dict.fromkeys(k for k in keys if k))[:QUICK_MAX]
    tables = {t["key"]: t for t in spatial_tables(db)}
    webmap = WebMap(database=db, title="")
    out = []
    for i, k in enumerate(keys):
        t = tables.get(k)
        if t is None:
            continue
        layer = MapLayer(webmap=webmap, schema=t["schema"], table=t["table"], geom_column=t["geom_column"],
                         srid=t["srid"], geom_type=t["geom_type"], style=default_style(i))
        try:
            layer.bbox = engine.extent(layer)
        except (engine.EngineError, ExplorerError):
            layer.bbox = []
        out.append(layer)
    return out
