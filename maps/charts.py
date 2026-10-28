"""نمودار روی داده‌های یک لایه نقشه: پاک‌سازی تنظیمات و تجمیع در PostGIS (فقط نتیجه به مرورگر می‌رسد).

انواع: کارت عددی (kpi)، میله‌ای (bar)، دایره‌ای (pie)، هیستوگرام (hist، با حالت درصد تجمعی)، سری زمانی (time)،
ستونی انباشته (stacked: دو ستون دسته‌ای) و پراکنش (scatter: دو ستون عددی، نمونه‌گیری‌شده).
اگر لایه روی همان ستون طبقه‌بندی عددی داشته باشد، هیستوگرام با همان مرزها بریده می‌شود و رنگ‌هایش از سیمبولوژی می‌آید.
"""
from __future__ import annotations

import psycopg
from psycopg import sql

from publish import engine

KINDS = {"kpi": "کارت عددی", "bar": "میله‌ای", "pie": "دایره‌ای", "hist": "هیستوگرام", "time": "سری زمانی",
         "stacked": "ستونی انباشته", "scatter": "پراکنش"}
AGGS = {"count": "تعداد", "sum": "جمع", "avg": "میانگین", "min": "کمینه", "max": "بیشینه"}
UNITS = {"day": "روز", "month": "ماه", "year": "سال"}
DATE_TYPES = {"date", "timestamp", "timestamptz"}
MAX_CHARTS_LIMIT = 20
PIE_MAX = 8
TIME_POINTS = 500
STACK_SERIES = 8  # بیشتر از این سری در «سایر» جمع می‌شود
SCATTER_POINTS = 2000


class ChartError(Exception):
    pass


def _int(value, default, lo, hi) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def clean(kind: str, data, types: dict[str, str]) -> dict:
    """تنظیمات معتبر یک نمودار؛ ستون‌ها باید در types (نام به نوع) باشند و با نوع نمودار جور شوند."""
    if kind not in KINDS:
        raise ChartError("نوع نمودار نامعتبر است.")
    data = data if isinstance(data, dict) else {}
    cfg: dict = {}
    if kind not in ("hist", "scatter"):
        agg = data.get("agg") if data.get("agg") in AGGS else "count"
        cfg["agg"] = agg
        value = data.get("value") if isinstance(data.get("value"), str) else ""
        if agg != "count":
            if types.get(value) not in engine.NUMERIC_TYPES:
                raise ChartError(f"برای «{AGGS[agg]}» یک ستون عددی انتخاب کنید.")
            cfg["value"] = value
    field = data.get("field") if isinstance(data.get("field"), str) else ""
    if kind == "kpi":
        return cfg
    if kind == "scatter":
        x, y = (data.get(k) if isinstance(data.get(k), str) else "" for k in ("x", "y"))
        if types.get(x) not in engine.NUMERIC_TYPES or types.get(y) not in engine.NUMERIC_TYPES:
            raise ChartError("برای پراکنش دو ستون عددی انتخاب کنید.")
        if x == y:
            raise ChartError("دو ستون پراکنش باید متفاوت باشند.")
        return {"x": x, "y": y}
    if field not in types:
        raise ChartError("ستون نمودار را انتخاب کنید.")
    cfg["field"] = field
    if kind in ("bar", "pie"):
        cfg["limit"] = _int(data.get("limit"), 10, 3, PIE_MAX if kind == "pie" else MAX_CHARTS_LIMIT)
        cfg["order"] = "label" if data.get("order") == "label" else "value"
    elif kind == "stacked":
        series = data.get("series") if isinstance(data.get("series"), str) else ""
        if series not in types or series == field:
            raise ChartError("برای ستونی انباشته دو ستون متفاوت (محور و سری) انتخاب کنید.")
        cfg["series"] = series
        cfg["limit"] = _int(data.get("limit"), 12, 3, MAX_CHARTS_LIMIT)
        cfg["percent"] = data.get("percent") is not False
    elif kind == "hist":
        if types[field] not in engine.NUMERIC_TYPES:
            raise ChartError("برای هیستوگرام یک ستون عددی انتخاب کنید.")
        cfg["bins"] = _int(data.get("bins"), 10, 3, 30)
        cfg["classes"] = data.get("classes") is not False
        cfg["cumulative"] = data.get("cumulative") is True
    else:
        if types[field] not in DATE_TYPES:
            raise ChartError("برای سری زمانی یک ستون تاریخ انتخاب کنید.")
        cfg["unit"] = data.get("unit") if data.get("unit") in UNITS else "month"
    return cfg


def title_for(kind: str, cfg: dict) -> str:
    """عنوان پیش‌فرض وقتی کاربر عنوان ننوشته است."""
    agg = AGGS[cfg.get("agg", "count")]
    what = f"{agg} {cfg['value']}" if cfg.get("value") else "تعداد عارضه‌ها"
    if kind == "kpi":
        return what
    if kind == "hist":
        return f"{'درصد تجمعی' if cfg.get('cumulative') else 'توزیع'} {cfg['field']}"
    if kind == "scatter":
        return f"{cfg['y']} در برابر {cfg['x']}"
    if kind == "stacked":
        return f"{what} بر اساس {cfg['field']} و {cfg['series']}"
    if kind == "time":
        return f"{what} به تفکیک {UNITS[cfg.get('unit', 'month')]}"
    return f"{what} بر اساس {cfg['field']}"


def class_breaks(layer, field: str) -> list[float]:
    """مرزهای طبقه‌بندی عددی لایه، اگر روی همین ستون باشد؛ وگرنه خالی."""
    st = layer.style or {}
    if st.get("mode") == "graduated" and st.get("field") == field:
        return [float(b) for b in st.get("breaks") or []]
    return []


def _agg(cfg: dict) -> sql.Composable:
    if cfg.get("agg", "count") == "count":
        return sql.SQL("count(*)")
    return sql.SQL("{}({}::float8)").format(sql.SQL(cfg["agg"]), sql.Identifier(cfg["value"]))


def _num(v):
    return None if v is None else round(float(v), 4)


def data(layer, kind: str, cfg: dict, bbox=None) -> dict:
    """نتیجه آماده رسم؛ bbox (طول و عرض) یعنی فقط عارضه‌های همان محدوده."""
    try:
        return _run(layer, kind, cfg, bbox)
    except psycopg.Error as exc:
        raise engine.EngineError(getattr(exc.diag, "message_primary", None) or str(exc)) from exc


def _run(layer, kind: str, cfg: dict, bbox) -> dict:
    with engine._connect(layer) as conn:
        meta = engine.table_meta(conn, layer.schema, layer.table)
        types = {n: t for n, t in meta["columns"] if n != layer.geom_column}
        cfg = clean(kind, cfg, types)
        rel = sql.Identifier(layer.schema, layer.table)
        where, params = [sql.SQL("true")], []
        if bbox:
            where.append(sql.SQL("{} && ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), {})").format(
                sql.Identifier(layer.geom_column), sql.Literal(layer.srid)))
            params += list(bbox)
        agg = _agg(cfg)

        def run(extra, tail, lead=(), more=()):
            # ترتیب پارامترها همان ترتیب %s در متن: SELECT، سپس محدوده (WHERE)، سپس انتهای پرسمان
            clause = sql.SQL(" AND ").join(where + extra)
            return conn.execute(sql.SQL("{} FROM {} WHERE {} {}").format(tail[0], rel, clause, tail[1]),
                                list(lead) + params + list(more)).fetchall()

        if kind == "kpi":
            row = run([], (sql.SQL("SELECT {}::float8, count(*)").format(agg), sql.SQL("")))[0]
            return {"value": _num(row[0]), "count": row[1]}
        if kind == "scatter":
            return _scatter(conn, rel, where, params, cfg)
        field = sql.Identifier(cfg["field"])
        notnull = [sql.SQL("{} IS NOT NULL").format(field)]
        if kind == "stacked":
            return _stacked(conn, rel, where, params, cfg, agg)
        if kind in ("bar", "pie"):
            order = sql.SQL("v DESC NULLS LAST, 1") if cfg["order"] == "value" else sql.SQL("1")
            rows = run(notnull, (sql.SQL("SELECT {}::text AS k, {}::float8 AS v").format(field, agg),
                                 sql.SQL("GROUP BY 1 ORDER BY {} LIMIT %s").format(order)), more=(cfg["limit"],))
            out = {"labels": [r[0] for r in rows], "values": [_num(r[1]) for r in rows], "other": None}
            if cfg.get("agg", "count") in ("count", "sum") and len(rows) >= cfg["limit"]:
                total = run(notnull, (sql.SQL("SELECT {}::float8").format(agg), sql.SQL("")))[0][0]
                rest = round(float(total or 0) - sum(v or 0 for v in out["values"]), 4)
                # جمع منفی هم جزو «سایر» است تا ردیف‌ها با کل جور شوند؛ فقط دایره‌ای مقدار منفی ندارد
                out["other"] = rest if (rest > 0 if kind == "pie" else rest != 0) else None
            return out
        if kind == "hist":
            col = sql.SQL("{}::float8").format(field)
            lo, hi, n = run(notnull, (sql.SQL("SELECT min({c}), max({c}), count(*)").format(c=col), sql.SQL("")))[0]
            if not n:
                return {"edges": [], "counts": [], "classes": False}
            breaks = sorted(set(class_breaks(layer, cfg["field"]))) if cfg["classes"] else []
            if not breaks and hi > lo:
                step = (hi - lo) / cfg["bins"]
                breaks = [lo + step * i for i in range(1, cfg["bins"])]
            counts = [0] * (len(breaks) + 1)
            if breaks:
                rows = run(notnull, (sql.SQL("SELECT width_bucket({}, %s::float8[]), count(*)").format(col),
                                     sql.SQL("GROUP BY 1")), lead=(breaks,))
                for b, c in rows:
                    counts[b] = c
            else:
                counts[0] = n
            # با محدوده دیده‌شده، کمینه و بیشینه ممکن است وسط مرزهای طبقه بیفتند؛ لبه‌ها باید مرتب بمانند
            edges = [min(lo, breaks[0]), *breaks, max(hi, breaks[-1])] if breaks else [lo, hi]
            return {"edges": [round(v, 6) for v in edges], "counts": counts,
                    "classes": bool(cfg["classes"] and class_breaks(layer, cfg["field"]))}
        rows = run(notnull, (sql.SQL("SELECT date_trunc(%s, {})::date AS d, {}::float8").format(field, agg),
                             sql.SQL("GROUP BY 1 ORDER BY 1 DESC LIMIT %s")), lead=(cfg["unit"],),
                    more=(TIME_POINTS,))
        rows.reverse()
        return {"labels": [r[0].isoformat() for r in rows], "values": [_num(r[1]) for r in rows], "unit": cfg["unit"]}


def _stacked(conn, rel, where, params, cfg, agg) -> dict:
    """مقدار هر (محور × سری)؛ فقط «limit» محور با بیشترین مجموع، و سری‌های بعد از هشتم در «سایر» (تعداد و جمع)."""
    x, s = sql.Identifier(cfg["field"]), sql.Identifier(cfg["series"])
    clause = sql.SQL(" AND ").join([*where, sql.SQL("{} IS NOT NULL").format(x), sql.SQL("{} IS NOT NULL").format(s)])
    rows = conn.execute(sql.SQL(
        "WITH b AS (SELECT {x}::text AS xs, {s}::text AS ss, {agg}::float8 AS v FROM {rel} WHERE {clause} GROUP BY 1, 2), "
        "t AS (SELECT xs FROM b GROUP BY xs ORDER BY sum(v) DESC NULLS LAST, xs LIMIT %s) "
        "SELECT b.xs, b.ss, b.v FROM b JOIN t USING (xs)").format(x=x, s=s, agg=agg, rel=rel, clause=clause),
        [*params, cfg["limit"]]).fetchall()
    xs_total: dict[str, float] = {}
    ss_total: dict[str, float] = {}
    for xs, ss, v in rows:
        xs_total[xs] = xs_total.get(xs, 0) + (v or 0)
        ss_total[ss] = ss_total.get(ss, 0) + (v or 0)
    labels = sorted(xs_total, key=lambda k: (-xs_total[k], k))
    names = sorted(ss_total, key=lambda k: (-ss_total[k], k))
    keep, rest = names[:STACK_SERIES], names[STACK_SERIES:]
    cells = {(xs, ss): v for xs, ss, v in rows}
    series = [{"name": n, "values": [_num(cells.get((xs, n)) or 0) for xs in labels]} for n in keep]
    if rest and cfg.get("agg", "count") in ("count", "sum"):
        series.append({"name": "سایر", "values": [_num(sum(cells.get((xs, n)) or 0 for n in rest)) for xs in labels]})
    return {"labels": labels, "series": series, "percent": cfg["percent"]}


def _scatter(conn, rel, where, params, cfg) -> dict:
    """نمونه‌ای پایدار (ترتیب md5 ردیف) تا نمودار با هر بار خواندن جابه‌جا نشود."""
    x, y = sql.Identifier(cfg["x"]), sql.Identifier(cfg["y"])
    clause = sql.SQL(" AND ").join([*where, sql.SQL("{} IS NOT NULL").format(x), sql.SQL("{} IS NOT NULL").format(y)])
    total = conn.execute(sql.SQL("SELECT count(*) FROM {} WHERE {}").format(rel, clause), params).fetchone()[0]
    rows = conn.execute(sql.SQL("SELECT {x}::float8, {y}::float8 FROM {rel} WHERE {clause} "
                                "ORDER BY md5(ctid::text) LIMIT %s").format(x=x, y=y, rel=rel, clause=clause),
                        [*params, SCATTER_POINTS]).fetchall()
    return {"points": [[_num(a), _num(b)] for a, b in rows], "total": total, "sampled": total > len(rows)}
