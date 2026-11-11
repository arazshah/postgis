"""
ذخیره‌ی نتیجه‌ی «یافتن عارضه» به‌صورت لایه‌ی تازه در همان پایگاه داده.

دو نوع لایه:
- جدول ثابت: عکس لحظه‌ی جست‌وجو؛ با تغییر داده‌ی اصلی عوض نمی‌شود (CREATE TABLE AS).
- نمای زنده: همان پرسش به‌صورت View؛ با تغییر داده‌ی اصلی خودکار به‌روز می‌شود و فضای اضافه نمی‌گیرد (فقط‌خواندنی).

پرسش از همان مشخصه‌ی امن `Finder.where()` ساخته می‌شود (نام‌ها از کاتالوگ و نقل‌قول‌شده، مقدارها پارامتر).
پارامترها پیش از اجرا با ClientCursor.mogrify درون متن می‌نشینند، چون دستورهای DDL پارامتر سمت‌سرور نمی‌گیرند.

گستره‌ی خروجی (scope): همه‌ی نتیجه | فقط انتخاب‌شده‌ها (با کلید اصلی) | همه به‌جز انتخاب‌شده‌ها؛
و «وارونه»: عارضه‌هایی که شرط را برآورده نمی‌کنند.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import psycopg
from psycopg import errors as pgerr
from psycopg import sql

from .explorer import Explorer, ExplorerError
from .find import OPS, Finder, FindError, _to4326
from .gdal import TABLE_RE

MAX_IDS = 5000
MAX_JOIN_COLS = 20
SCOPES = ("all", "selected", "except")
KINDS = ("table", "view")
SCHEMA = "public"
TIMEOUT = "10min"
_TYPED = re.compile(r"^(MULTI)?(POINT|LINESTRING|POLYGON)$")


@dataclass
class Plan:
    query: sql.Composable
    params: list
    name: str
    kind: str
    replace: bool
    geom_col: str = ""
    pk: str = ""
    out_names: list = field(default_factory=list)
    comment: str = ""
    source: str = ""


# ---------------------------------------------------------------------- توضیح فارسی از جست‌وجو
_OP_TITLE = {}
for _ops in reversed(list(OPS.values())):
    _OP_TITLE.update({k: t for k, t, _n in _ops})
_REL_TITLE = {"intersects": "قطع می‌کند", "within": "کاملاً داخل باشد", "contains": "در بر بگیرد",
              "dwithin": "تا فاصله‌ی", "touches": "مجاور باشد", "disjoint": "هیچ تماسی نداشته باشد"}


def _conds_text(conds) -> str:
    out = []
    for c in conds or []:
        if not isinstance(c, dict):
            continue
        v = str(c.get("v") or "").strip()
        if c.get("v2"):
            v += f" تا {str(c['v2']).strip()}"
        out.append(f"{c.get('col')} {_OP_TITLE.get(c.get('op'), c.get('op'))}" + (f" «{v}»" if v else ""))
    return "، ".join(out)


def describe(spec: dict, opts: dict | None = None) -> str:
    """یک یا دو جمله‌ی فارسی که به‌عنوان توضیح روی جدول/نما ذخیره می‌شود."""
    opts = opts or {}
    parts = [f"نتیجه‌ی یافتن عارضه روی {spec.get('layer')}"]
    cond = _conds_text(spec.get("conds"))
    if cond:
        join = "یکی از" if spec.get("match") == "any" else "همه‌ی"
        parts.append(f"شرط ({join} این‌ها): {cond}")
    sp = spec.get("spatial")
    if isinstance(sp, dict):
        t = sp.get("target") or {}
        rel = _REL_TITLE.get(sp.get("rel"), "")
        if sp.get("rel") == "dwithin":
            rel += f" {sp.get('dist')} متر"
        kind = t.get("kind")
        if kind == "layer":
            extra = _conds_text(t.get("conds"))
            tgt = f"لایه‌ی {t.get('layer')}" + (f" با شرط {extra}" if extra else "")
        else:
            tgt = {"shape": "شکل کشیده‌شده روی نقشه", "circle": "دایره‌ی کشیده‌شده روی نقشه",
                   "extent": "محدوده‌ی نقشه"}.get(kind, "")
        parts.append(f"شرط مکانی: {rel} نسبت به {tgt}")
    if opts.get("invert"):
        parts.append("وارونه (عارضه‌هایی که شرط را برآورده نمی‌کنند)")
    scope = opts.get("scope")
    if scope == "selected":
        parts.append("فقط عارضه‌های انتخاب‌شده")
    elif scope == "except":
        parts.append("همه به‌جز عارضه‌های انتخاب‌شده")
    return " — ".join(parts)[:900]


# ---------------------------------------------------------------------- گزینه‌های ذخیره
def parse_opts(raw) -> dict:
    if not isinstance(raw, dict):
        raise FindError("گزینه‌های ذخیره نامعتبر است.")
    name = str(raw.get("name") or "").strip().lower()
    if not TABLE_RE.match(name):
        raise FindError("نام لایه: حروف کوچک لاتین، رقم و _ (مثلاً schools_narmak).")
    kind = raw.get("kind") or "table"
    scope = raw.get("scope") or "all"
    if kind not in KINDS or scope not in SCOPES:
        raise FindError("گزینه‌های ذخیره نامعتبر است.")
    ids = raw.get("ids") or []
    if not isinstance(ids, list):
        raise FindError("فهرست انتخاب نامعتبر است.")
    ids = list(dict.fromkeys(str(x) for x in ids))
    if len(ids) > MAX_IDS:
        raise FindError(f"حداکثر {MAX_IDS:,} عارضه را می‌شود دستی انتخاب کرد.")
    if scope != "all" and not ids:
        raise FindError("هیچ عارضه‌ای انتخاب نشده است.")
    cols = raw.get("cols")
    if cols is not None and not isinstance(cols, list):
        raise FindError("ستون‌های انتخاب‌شده نامعتبر است.")
    join = raw.get("join_cols") or []
    if not isinstance(join, list) or len(join) > MAX_JOIN_COLS:
        raise FindError(f"حداکثر {MAX_JOIN_COLS} ستون از لایه‌ی هدف را می‌شود آورد.")
    return {"name": name, "kind": kind, "scope": scope, "ids": ids if scope != "all" else [],
            "invert": bool(raw.get("invert")), "cols": [str(c) for c in cols] if cols is not None else None,
            "join_cols": [str(c) for c in join], "dist_col": bool(raw.get("dist_col")),
            "srid": "4326" if str(raw.get("srid")) == "4326" else "keep", "replace": bool(raw.get("replace"))}


# ---------------------------------------------------------------------- ساخت پرسش
def _unique(name: str, used: set) -> str:
    name = name[:63]
    cand, i = name, 2
    while cand in used:
        suffix = f"_{i}"
        cand, i = name[:63 - len(suffix)] + suffix, i + 1
    used.add(cand)
    return cand


def build(finder: Finder, spec: dict, raw_opts: dict) -> Plan:
    """اعتبارسنجی کامل و ساخت SELECT نهایی؛ به پایگاه داده چیزی نمی‌نویسد."""
    opts = parse_opts(raw_opts)
    t, info, where, wparams = finder.where(spec)
    if opts["name"] in {finder.table(spec["layer"]).name} and SCHEMA == t.schema:
        raise FindError("نام لایه‌ی تازه نباید با لایه‌ی اصلی یکی باشد.")
    cols = finder.cols(t)
    plain = [c for c in cols if not c["spatial"]]
    pks = [c for c in cols if c["pk"]]
    pk = pks[0]["name"] if len(pks) == 1 and not pks[0]["spatial"] else ""
    by_name = {c["name"]: c for c in plain}

    wanted = opts["cols"] if opts["cols"] is not None else [c["name"] for c in plain]
    bad = [c for c in wanted if c not in by_name]
    if bad:
        raise FindError(f"ستون «{bad[0]}» در لایه نیست.")
    keep = [c["name"] for c in plain if c["name"] in set(wanted) or c["name"] == pk]  # ترتیب اصلی؛ کلید همیشه می‌ماند
    if not keep and not info:
        raise FindError("دست‌کم یک ستون را نگه دارید.")
    if opts["scope"] != "all" and not pk:
        raise FindError("انتخاب دستی فقط برای لایه‌ای ممکن است که کلید اصلی یگانه دارد.")

    used = set(keep)
    geom_out = ""
    geom_expr = None
    if info:
        geom_out = info["column"]
        used.add(geom_out)
        want4326 = opts["srid"] == "4326"
        ta = info["type"].upper() if info["type"] else ""
        if want4326 or info["geography"]:
            g = _to4326("a", info) if (want4326 or info["srid"] != 4326) else \
                sql.SQL("a.{}::geometry").format(sql.Identifier(info["column"]))
            typ = sql.SQL("geometry({}, 4326)").format(sql.SQL(ta)) if _TYPED.match(ta) else sql.SQL("geometry")
            geom_expr = sql.SQL("({})::{}").format(g, typ)
        else:
            geom_expr = sql.SQL("a.{}").format(sql.Identifier(info["column"]))

    # ستون‌هایی از لایه‌ی هدف و فاصله (اتصال مکانی؛ نزدیک‌ترین/اولین عارضه‌ی هدف)
    join_sql, jparams, join_out = sql.SQL(""), [], []
    if opts["join_cols"] or opts["dist_col"]:
        sp = spec.get("spatial")
        tgt = (sp or {}).get("target") if isinstance(sp, dict) else None
        if not (isinstance(tgt, dict) and tgt.get("kind") == "layer"):
            raise FindError("ستون از لایه‌ی هدف فقط وقتی شرط مکانی «لایه‌ای دیگر» است ممکن است.")
        if sp["rel"] == "disjoint":
            raise FindError("برای «هیچ تماسی نداشته باشد» عارضه‌ی هدفی وجود ندارد که ستونش را بیاورید.")
        if opts["dist_col"] and sp["rel"] != "dwithin":
            raise FindError("ستون فاصله فقط برای رابطه‌ی «تا فاصله‌ی» ساخته می‌شود.")
        b, _binfo, cond_b, jparams, dist = finder.layer_rel(info, sp)
        if b.schema == SCHEMA and b.name == opts["name"]:
            raise FindError("نام لایه‌ی تازه نباید با لایه‌ی هدف یکی باشد.")
        bcols = {c["name"]: c for c in finder.cols(b) if not c["spatial"]}
        items = []
        for col in opts["join_cols"]:
            if col not in bcols:
                raise FindError(f"ستون «{col}» در لایه‌ی هدف نیست.")
            alias = _unique(f"{b.name}_{col}", used)
            items.append(sql.SQL("b.{} AS {}").format(sql.Identifier(col), sql.Identifier(alias)))
            join_out.append(alias)
        order = sql.SQL("")
        if opts["dist_col"]:
            alias = _unique("distance_m", used)
            items.append(sql.SQL("round({}::numeric, 1) AS {}").format(dist, sql.Identifier(alias)))
            join_out.append(alias)
            order = sql.SQL(" ORDER BY {}").format(dist)
        join_sql = sql.SQL(" LEFT JOIN LATERAL (SELECT {items} FROM {B} AS b WHERE {c}{o} LIMIT 1) AS j ON true").format(
            items=sql.SQL(", ").join(items), B=sql.Identifier(b.schema, b.name), c=cond_b, o=order)
        # ستون‌های j با نام خروجی انتخاب می‌شوند
    select = [sql.SQL("a.{}").format(sql.Identifier(n)) for n in keep]
    if geom_expr is not None:
        select.append(sql.SQL("{} AS {}").format(geom_expr, sql.Identifier(geom_out)))
    select += [sql.SQL("j.{}").format(sql.Identifier(n)) for n in join_out]

    conds, params = [], list(jparams)
    if info:
        conds.append(sql.SQL("a.{} IS NOT NULL").format(sql.Identifier(info["column"])))
    conds.append(sql.SQL("NOT COALESCE(({}), false)").format(where) if opts["invert"] else sql.SQL("({})").format(where))
    params += wparams
    if opts["scope"] != "all":
        op = sql.SQL("= ANY(%s)") if opts["scope"] == "selected" else sql.SQL("<> ALL(%s)")
        conds.append(sql.SQL("a.{}::text {}").format(sql.Identifier(pk), op))
        params.append(opts["ids"])
    query = sql.SQL("SELECT {sel} FROM {rel} AS a{join} WHERE {w}").format(
        sel=sql.SQL(", ").join(select), rel=sql.Identifier(t.schema, t.name), join=join_sql,
        w=sql.SQL(" AND ").join(conds))
    return Plan(query=query, params=params, name=opts["name"], kind=opts["kind"], replace=opts["replace"],
                geom_col=geom_out, pk=pk if pk in keep else "", out_names=keep + ([geom_out] if geom_out else []) + join_out,
                comment=describe(spec, opts), source=t.qualified)


def statement_text(conn, plan: Plan) -> str:
    """دستور کامل (CREATE … AS SELECT …) با مقدارهای جایگذاری‌شده."""
    body = psycopg.ClientCursor(conn).mogrify(plan.query, plan.params)
    head = "CREATE VIEW" if plan.kind == "view" else "CREATE TABLE"
    return f"{head} {SCHEMA}.{plan.name} AS\n{body}"


# ---------------------------------------------------------------------- اجرا
def _friendly(exc: Exception) -> str:
    if isinstance(exc, pgerr.QueryCanceled):
        return "ساخت لایه بیش از ۱۰ دقیقه طول کشید؛ شرط را محدودتر کنید."
    if isinstance(exc, pgerr.DependentObjectsStillExist):
        return "لایه‌ی هم‌نام جای دیگری (مثلاً نما یا نقشه) استفاده شده و جایگزین نمی‌شود؛ نام دیگری بدهید."
    if isinstance(exc, pgerr.InsufficientPrivilege):
        return "برای ساخت لایه در این پایگاه داده دسترسی ندارید."
    if isinstance(exc, pgerr.DiskFull):
        return "فضای پایگاه داده پر است؛ فضا آزاد کنید یا «نمای زنده» را بسازید."
    msg = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    return f"ساخت لایه ممکن نشد: {msg[:200]}"


def check_name(ex: Explorer, plan: Plan) -> None:
    """پیش از صف شدن: آیا نام آزاد است (یا جایگزینی خواسته شده)؟"""
    if any(t.schema == SCHEMA and t.name == plan.name for t in ex.tables()) and not plan.replace:
        raise FindError(f"لایه‌ای به نام {plan.name} از قبل هست؛ نام دیگری بدهید یا «جایگزین شود» را بزنید.")


def create(db, ex: Explorer, plan: Plan, step=lambda pct, text: None) -> dict:
    """ساخت جدول/نما. نتیجه: {"table", "rows", "kind"}."""
    from .provisioner import Provisioner

    target = sql.Identifier(SCHEMA, plan.name)
    try:
        with ex.connect(read_only=False, as_owner=True) as conn:
            conn.execute(sql.SQL("SET statement_timeout = {}").format(sql.Literal(TIMEOUT)))
            step(10, "بررسی نام")
            row = conn.execute("SELECT c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                               "WHERE n.nspname = %s AND c.relname = %s", (SCHEMA, plan.name)).fetchone()
            if row:
                if not plan.replace:
                    raise FindError(f"لایه‌ای به نام {plan.name} از قبل هست.")
                if row[0] not in ("r", "v"):
                    raise FindError(f"{plan.name} جدول یا نمای ساده نیست و جایگزین نمی‌شود.")
                conn.execute(sql.SQL("DROP {} {}").format(sql.SQL("VIEW" if row[0] == "v" else "TABLE"), target))
            step(25, "ساخت نمای زنده" if plan.kind == "view" else "ساخت جدول از نتیجه")
            body = sql.SQL(psycopg.ClientCursor(conn).mogrify(plan.query, plan.params))
            head = sql.SQL("CREATE {} {} AS ").format(sql.SQL("VIEW" if plan.kind == "view" else "TABLE"), target)
            conn.execute(head + body)
            if plan.kind == "table":
                step(65, "کلید اصلی")
                if plan.pk:
                    conn.execute(sql.SQL("ALTER TABLE {} ADD PRIMARY KEY ({})").format(target, sql.Identifier(plan.pk)))
                else:
                    gid = _unique("gid", set(plan.out_names))
                    conn.execute(sql.SQL("ALTER TABLE {} ADD COLUMN {} serial PRIMARY KEY").format(
                        target, sql.Identifier(gid)))
                if plan.geom_col:
                    step(80, "نمایه‌ی مکانی")
                    conn.execute(sql.SQL("CREATE INDEX ON {} USING gist ({})").format(target, sql.Identifier(plan.geom_col)))
                step(92, "آماده‌سازی نهایی")
                conn.execute(sql.SQL("ANALYZE {}").format(target))
            conn.execute(sql.SQL("COMMENT ON {} {} IS {}").format(
                sql.SQL("VIEW" if plan.kind == "view" else "TABLE"), target, sql.Literal(plan.comment)))
            rows = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(target)).fetchone()[0]
            conn.commit()
    except (FindError, ExplorerError):
        raise
    except psycopg.Error as exc:
        raise FindError(_friendly(exc)) from exc
    Provisioner.for_server(db.server).reassign_browser_objects(db.db_name, db.role_name)
    return {"table": f"{SCHEMA}.{plan.name}", "rows": rows, "kind": plan.kind}
