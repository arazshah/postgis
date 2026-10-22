"""
نقشه چندلایه به پروژه QGIS 3 (.qgs): همان لایه‌ها، ترتیب، رنگ‌آمیزی (تک‌رنگ، طبقه‌بندی عددی، دسته‌ای) و برچسب.

دو کاربرد:
- دانلود برای QGIS دسکتاپ: اتصال به پایگاه داده کاربر بدون رمز (QGIS بار اول رمز را می‌پرسد).
- انتشار WMS/WFS: به publish.ows داده می‌شود و همان مسیر پاک‌سازی پروژه‌های آپلودی را طی می‌کند
  (اتصال هر لایه آنجا با نقش فقط‌خواندنی همین پایگاه داده جایگزین می‌شود).
"""
from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement, tostring

from publish import engine
from publish.styles import PALETTES

from . import services

NOVAL = "#9AA5A8"
PX_MM = 0.2646  # یک پیکسل CSS در ۹۶ DPI


def desktop_connection(db) -> str:
    """اتصال بدون رمز برای QGIS دسکتاپ (رمز را خود کاربر وارد می‌کند)."""
    ssl = "require" if db.server.sslmode in ("require", "verify-ca", "verify-full") else "prefer"
    return f"dbname='{db.db_name}' host={db.host} port={int(db.port)} user='{db.role_name}' sslmode={ssl}"


def _rgba(hex_color: str, alpha: float = 1.0) -> str:
    h = (hex_color or "#000000").lstrip("#")
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        r, g, b = 0, 0, 0
    return f"{r},{g},{b},{round(max(0.0, min(1.0, alpha)) * 255)}"


def pick(pal: list[str], n: int) -> list[str]:
    """همان انتخاب رنگ map-page.js تا رنگ‌های QGIS با نقشه وب یکی باشد."""
    if n >= len(pal):
        return pal[:]
    return [pal[round(i * (len(pal) - 1) / max(1, n - 1))] for i in range(n)]


def _kind(geom_type: str) -> str:
    g = (geom_type or "").upper()
    if "POINT" in g:
        return "Point"
    if "LINE" in g:
        return "Line"
    return "Polygon"


def _wkb(geom_type: str) -> str:
    g = (geom_type or "").upper()
    names = {"POINT": "Point", "MULTIPOINT": "MultiPoint", "LINESTRING": "LineString",
             "MULTILINESTRING": "MultiLineString", "POLYGON": "Polygon", "MULTIPOLYGON": "MultiPolygon"}
    return names.get(g, "Unknown")


def _opt(parent: Element, name: str, value) -> None:
    SubElement(parent, "Option", {"name": name, "type": "QString", "value": str(value)})


def _symbol(parent: Element, name: str, kind: str, color: str, st: dict) -> Element:
    op = float(st.get("opacity", 0.75))
    stype = {"Point": "marker", "Line": "line", "Polygon": "fill"}[kind]
    sym = SubElement(parent, "symbol", {"name": name, "type": stype, "alpha": "1", "clip_to_extent": "1",
                                        "force_rhr": "0"})
    size = float(st.get("size", 6))
    outline = st.get("outline", "#FFFFFF")
    if kind == "Point":
        layer = SubElement(sym, "layer", {"class": "SimpleMarker", "enabled": "1", "locked": "0", "pass": "0"})
        opts = SubElement(layer, "Option", {"type": "Map"})
        _opt(opts, "name", "circle")
        _opt(opts, "color", _rgba(color, min(1, op + 0.15)))
        _opt(opts, "outline_color", _rgba(outline))
        _opt(opts, "outline_width", round(PX_MM, 3))
        _opt(opts, "outline_width_unit", "MM")
        _opt(opts, "size", round(size * 2 * PX_MM, 3))
        _opt(opts, "size_unit", "MM")
    elif kind == "Line":
        layer = SubElement(sym, "layer", {"class": "SimpleLine", "enabled": "1", "locked": "0", "pass": "0"})
        opts = SubElement(layer, "Option", {"type": "Map"})
        _opt(opts, "line_color", _rgba(color, min(1, op + 0.2)))
        _opt(opts, "line_width", round(max(1, size / 2) * PX_MM, 3))
        _opt(opts, "line_width_unit", "MM")
        _opt(opts, "capstyle", "round")
        _opt(opts, "joinstyle", "round")
    else:
        layer = SubElement(sym, "layer", {"class": "SimpleFill", "enabled": "1", "locked": "0", "pass": "0"})
        opts = SubElement(layer, "Option", {"type": "Map"})
        _opt(opts, "color", _rgba(color, op))
        _opt(opts, "style", "solid")
        _opt(opts, "outline_color", _rgba(outline, 0.9))
        _opt(opts, "outline_width", round(0.8 * PX_MM, 3))
        _opt(opts, "outline_width_unit", "MM")
    return sym


def _renderer(ml: Element, kind: str, st: dict) -> None:
    mode, field = st.get("mode"), st.get("field")
    if mode == "graduated" and field and st.get("breaks"):
        breaks = [float(b) for b in st["breaks"]]
        pal = pick(PALETTES.get(st.get("palette"), PALETTES["YlOrRd"]), len(breaks) + 1)
        r = SubElement(ml, "renderer-v2", {"type": "graduatedSymbol", "attr": field, "graduatedMethod": "GraduatedColor",
                                           "symbollevels": "0", "forceraster": "0", "enableorderby": "0"})
        ranges, symbols = SubElement(r, "ranges"), SubElement(r, "symbols")
        edges = [-1e15, *breaks, 1e15]
        for i, color in enumerate(pal):
            lo, hi = edges[i], edges[i + 1]
            label = (f"کمتر از {hi:g}" if i == 0 else f"{lo:g} و بیشتر" if i == len(pal) - 1 else f"{lo:g} تا {hi:g}")
            SubElement(ranges, "range", {"lower": repr(lo), "upper": repr(hi), "symbol": str(i), "label": label,
                                         "render": "true"})
            _symbol(symbols, str(i), kind, color, st)
        return
    if mode == "categorized" and field and st.get("categories"):
        r = SubElement(ml, "renderer-v2", {"type": "categorizedSymbol", "attr": field, "symbollevels": "0",
                                           "forceraster": "0", "enableorderby": "0"})
        cats, symbols = SubElement(r, "categories"), SubElement(r, "symbols")
        for i, c in enumerate(st["categories"]):
            SubElement(cats, "category", {"value": c["value"], "label": c["value"], "symbol": str(i),
                                          "render": "true", "type": "string"})
            _symbol(symbols, str(i), kind, c["color"], st)
        i = len(st["categories"])
        # مقدار خالی در QGIS یعنی «همه مقدارهای دیگر»
        SubElement(cats, "category", {"value": "", "label": "سایر", "symbol": str(i), "render": "true",
                                      "type": "string"})
        _symbol(symbols, str(i), kind, NOVAL, st)
        return
    r = SubElement(ml, "renderer-v2", {"type": "singleSymbol", "symbollevels": "0", "forceraster": "0",
                                       "enableorderby": "0"})
    _symbol(SubElement(r, "symbols"), "0", kind, st.get("color", "#0F5C59"), st)


def _labeling(ml: Element, kind: str, st: dict) -> None:
    if not st.get("label"):
        return
    ml.set("labelsEnabled", "1")
    lab = SubElement(ml, "labeling", {"type": "simple"})
    s = SubElement(lab, "settings", {"calloutType": "simple"})
    SubElement(s, "text-style", {"fieldName": st["label"], "isExpression": "0", "fontFamily": "Vazirmatn",
                                 "fontSize": str(round(int(st.get("label_size", 12)) * 0.75, 1)),
                                 "fontSizeUnit": "Point", "textColor": _rgba(st.get("label_color", "#1B2B2F")),
                                 "textOpacity": "1", "namedStyle": "Regular"})
    SubElement(s, "text-buffer", {"bufferDraw": "1", "bufferSize": "1", "bufferSizeUnits": "MM",
                                  "bufferColor": "255,255,255,235", "bufferOpacity": "1"})
    # ۲: موازی خط، ۰: اطراف نقطه، ۱: روی مرکز چندضلعی
    SubElement(s, "placement", {"placement": {"Line": "2", "Point": "6", "Polygon": "1"}[kind], "dist": "1.5",
                                "distUnits": "MM"})
    SubElement(s, "rendering", {"obstacle": "1", "scaleVisibility": "0", "upsidedownLabels": "0"})


def _srs(parent: Element, srid: int) -> None:
    srs = SubElement(parent, "spatialrefsys", {"nativeFormat": "Wkt"})
    SubElement(srs, "authid").text = f"EPSG:{int(srid)}"
    SubElement(srs, "srid").text = str(int(srid))


def _datasource(conn: str, layer, pk: str) -> str:
    def ident(v):
        return '"' + v.replace('"', '""') + '"'

    parts = [conn]
    if pk:
        parts.append(f"key='{pk}'")
    parts += [f"srid={int(layer.srid)}", f"type={_wkb(layer.geom_type)}", "checkPrimaryKeyUnicity='0'",
              f"table={ident(layer.schema)}.{ident(layer.table)} ({layer.geom_column})"]
    return " ".join(parts)


def build(webmap, conn: str) -> bytes:
    """فایل .qgs؛ conn رشته اتصال QGIS (QgsDataSourceUri) بدون جدول است."""
    layers = list(webmap.layers.all())
    root = Element("qgis", {"version": "3.34.4-Prizren", "projectname": webmap.title})
    SubElement(root, "title").text = webmap.title
    _srs(SubElement(root, "projectCrs"), 3857)
    tree = SubElement(root, "layer-tree-group")
    projectlayers = SubElement(root, "projectlayers")
    order = SubElement(root, "layerorder")
    used: set[str] = set()
    for layer in layers:
        lid = f"gp_{webmap.slug}_{layer.pk}"
        name = layer.display_title
        n = 2
        while name in used:  # نام لایه در WMS باید یکتا باشد
            name, n = f"{layer.display_title} ({n})", n + 1
        used.add(name)
        try:
            pk = engine.describe(layer)["pk"]
        except Exception:  # noqa: BLE001  جدول در دسترس نیست؛ پروژه بدون کلید ساخته می‌شود
            pk = ""
        source = _datasource(conn, layer, pk)
        SubElement(tree, "layer-tree-layer", {
            "id": lid, "name": name, "providerKey": "postgres", "source": source, "expanded": "1",
            "checked": "Qt::Checked" if layer.visible else "Qt::Unchecked"})
        kind = _kind(layer.geom_type)
        ml = SubElement(projectlayers, "maplayer", {"type": "vector", "geometry": kind, "wkbType": _wkb(layer.geom_type),
                                                    "labelsEnabled": "0", "hasScaleBasedVisibilityFlag": "0",
                                                    "styleCategories": "AllStyleCategories"})
        SubElement(ml, "id").text = lid
        SubElement(ml, "datasource").text = source
        SubElement(ml, "layername").text = name
        _srs(SubElement(ml, "srs"), layer.srid)
        SubElement(ml, "provider", {"encoding": "UTF-8"}).text = "postgres"
        st = services.layer_style(layer)
        _renderer(ml, kind, st)
        _labeling(ml, kind, st)
        SubElement(ml, "blendMode").text = "0"
        SubElement(ml, "layerOpacity").text = "1"
        SubElement(order, "layer", {"id": lid})
    props = SubElement(root, "properties")
    gui = SubElement(props, "Gui")
    SubElement(gui, "SelectionColorRedPart", {"type": "int"}).text = "255"
    xml = "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n" + tostring(root, encoding="unicode")
    return xml.encode("utf-8")


def for_publishing(webmap) -> bytes:
    """برای publish.ows: اتصال ساختگی که پاک‌سازی پروژه آن را با نقش فقط‌خواندنی همین پایگاه داده عوض می‌کند."""
    return build(webmap, "dbname='gp'")
