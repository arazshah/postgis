#!/usr/bin/env python3
"""ساخت نسخه‌ی چاپی کتاب «پایگاه داده مکانی ابری».

    python docs/book/build.py            # ساخت کامل: out/book.pdf (جلد رو + متن + جلد پشت) و out/cover-spread.pdf
    python docs/book/build.py --html     # فقط HTML (برای پیش‌نمایش سریع)
    python docs/book/build.py --check    # بررسی: اجرای همه‌ی SQLها، وجود تصویرها، واژه‌ی ممنوع

منبع: book.json (ترتیب بخش‌ها و فصل‌ها) و chapters/*.md (Markdown پاندوک با سرآیند YAML).
کدهای ```{.sql .run} روی پایگاه نمونه اجرا و جدول نتیجه زیرشان چاپ می‌شود (نتیجه در results/ نگه داشته می‌شود
تا ساخت بدون پایگاه هم ممکن باشد). اتصال: BOOK_PG (پیش‌فرض پایگاه نمایشی docs/help-video).
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
RES = HERE / "results"
DSN = os.environ.get("BOOK_PG", "host=localhost user=postgres password=postgres dbname=gp_tehran_gis")
FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
BANNED = ("ژئوپایگاه",)  # نام تجاری در متن کتاب نمی‌آید؛ «پایگاه داده مکانی ابری»


def fa(x) -> str:
    return str(x).translate(FA)


def load() -> dict:
    return json.loads((HERE / "book.json").read_text(encoding="utf-8"))


def parse_md(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    meta = {}
    if text.startswith("---\n"):
        _, fm, text = text.split("---\n", 2)
        meta = yaml.safe_load(fm) or {}
    return meta, text


# ---------------------------------------------------------------- اجرای SQL
USED: set[str] = set()


def run_sql(sql: str, limit: int) -> dict:
    key = hashlib.sha1(f"{limit}\n{sql}".encode()).hexdigest()[:16]
    USED.add(key)
    cache = RES / f"{key}.json"
    if cache.exists() and not os.environ.get("BOOK_RERUN"):
        return json.loads(cache.read_text(encoding="utf-8"))
    import psycopg

    with psycopg.connect(DSN) as conn:
        conn.execute("SET statement_timeout = '30s'")
        cur = conn.cursor()
        res = {"cols": [], "rows": [], "total": 0, "msg": ""}
        statements = [s for s in split_sql(sql) if s.strip()]
        for st in statements:
            cur.execute(st)
            if cur.description:
                rows = cur.fetchall()
                shown = [[wkt(conn, v) for v in r] for r in rows[:limit]]
                res = {"cols": [d.name for d in cur.description], "rows": [[cell(v) for v in r] for r in shown],
                       "total": len(rows), "msg": ""}
            else:
                res = {"cols": [], "rows": [], "total": 0, "msg": cur.statusmessage or ""}
        conn.rollback()  # کتاب هیچ چیزی را در پایگاه نمونه تغییر نمی‌دهد
    RES.mkdir(exist_ok=True)
    cache.write_text(json.dumps(res, ensure_ascii=False, indent=0), encoding="utf-8")
    return res


def split_sql(sql: str) -> list[str]:
    out, buf, q = [], [], None
    for ch in sql:
        if q:
            q = None if ch == q else q
        elif ch in "'\"":
            q = ch
        elif ch == ";":
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    out.append("".join(buf))
    return [re.sub(r"^\s*--.*$", "", s, flags=re.M).strip() and s for s in out]


HEXGEOM = re.compile(r"^0[01][0-9A-F]{16,}$")


def wkt(conn, v):
    """هندسه‌ی خام (EWKB هگز) را مثل کنسول سامانه به WKT خوانا تبدیل می‌کند."""
    if isinstance(v, str) and HEXGEOM.match(v):
        return conn.execute("SELECT ST_AsText(%s::geometry)", (v,)).fetchone()[0]
    return v


def cell(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, float):
        v = round(v, 4)
    s = str(v)
    return s if len(s) <= 64 else s[:60] + "…"


def result_html(res: dict) -> str:
    if not res["cols"]:
        return f'<p class="result-msg" dir="ltr" style="font:8pt var(--f-mono);color:#7b8789;margin:-1mm 0 4mm">{html.escape(res["msg"])}</p>'
    head = "".join(f"<th>{html.escape(c)}</th>" for c in res["cols"])
    body = "".join("<tr>" + "".join(f"<td>{html.escape(v)}</td>" for v in r) + "</tr>" for r in res["rows"])
    more = ""
    if res["total"] > len(res["rows"]):
        more = f'<tr><td colspan="{len(res["cols"])}" style="color:#7b8789">… ({res["total"]} rows)</td></tr>'
    return f'<table class="result"><thead><tr>{head}</tr></thead><tbody>{body}{more}</tbody></table>'


RUN_RE = re.compile(r"```\{\.sql \.run(?P<attrs>[^}]*)\}\n(?P<sql>.*?)\n```", re.S)


def expand_runs(md: str) -> str:
    def rep(m):
        attrs, sql = m.group("attrs"), m.group("sql")
        lim = re.search(r"rows=(\d+)", attrs)
        res = run_sql(sql, int(lim.group(1)) if lim else 6)
        return f"```sql\n{sql}\n```\n\n```{{=html}}\n{result_html(res)}\n```\n"
    return RUN_RE.sub(rep, md)


# ---------------------------------------------------------------- Markdown → HTML
def pandoc(md: str) -> str:
    p = subprocess.run(["pandoc", "-f", "markdown+fenced_divs+bracketed_spans+pipe_tables+implicit_figures+raw_html",
                        "-t", "html5", "--mathml", "--wrap=none", "--highlight-style=pygments"],
                       input=md, capture_output=True, text=True, check=True)
    return p.stdout


def number_body(body: str, chno: int, marks: list) -> tuple[str, list]:
    """شماره‌ی بخش (۳-۲) و شکل (شکل ۳-۲) و نشانه‌ی صفحه برای فهرست."""
    secs, fig = [], [0]

    def h2(m):
        secs.append(None)
        n = len(secs)
        title = re.sub(r"<[^>]+>", "", m.group(2))
        mk = f"@@S{chno}_{n}@@"
        secs[-1] = (n, title, mk)
        return f'<h2{m.group(1)}><span class="mk">{mk}</span><bdi class="sn">{fa(chno)}-{fa(n)}</bdi> <bdi>{m.group(2)}</bdi></h2>'
    body = re.sub(r"<h2([^>]*)>(.*?)</h2>", h2, body, flags=re.S)

    def cap(m):
        fig[0] += 1
        return f'<figcaption><span class="fno">شکل {fa(chno)}-{fa(fig[0])}</span>{m.group(1)}</figcaption>'
    body = re.sub(r"<figcaption>(.*?)</figcaption>", cap, body, flags=re.S)
    # نمودارهای SVG درون صفحه گذاشته می‌شوند تا قلم فارسی کتاب در آن‌ها هم به کار برود
    def inline_svg(m):
        f = HERE / m.group(1).removeprefix("../")
        return f.read_text(encoding="utf-8") if f.exists() else m.group(0)
    body = re.sub(r'<img src="(\.\./figures/[^"]+\.svg)"[^>]*/?>', inline_svg, body)
    # کلاس‌های تصویر (pandoc کلاس img را روی img می‌گذارد؛ برای figure هم لازم است)
    body = re.sub(r'<figure>\s*<img([^>]*)class="([^"]*)"', lambda m: f'<figure class="{m.group(2)}"><img{m.group(1)}class="{m.group(2)}"', body)
    return body, secs


def level_dots(n: int) -> str:
    return '<span class="lvl">' + "".join(f'<i class="{"on" if i < n else ""}"></i>' for i in range(3)) + "</span>"


LEVELS = {1: "مبتدی", 2: "متوسط", 3: "پیشرفته"}


def opener(chno: int, meta: dict, art: str, secs=()) -> str:
    goals = "".join(f"<li>{html.escape(g)}</li>" for g in meta.get("goals", []))
    lvl = int(meta.get("level", 1))
    chips = [f'<span>سطح: <b>{LEVELS[lvl]}</b> {level_dots(lvl)}</span>']
    if meta.get("time"):
        chips.append(f'<span>زمان مطالعه: <b>{fa(meta["time"])}</b></span>')
    if meta.get("prereq"):
        chips.append(f'<span>پیش‌نیاز: <b>{fa(meta["prereq"])}</b></span>')
    outline = ""
    if secs:
        li = "".join(f'<li><bdi class="n">{fa(chno)}-{fa(n)}</bdi> <bdi>{html.escape(t)}</bdi></li>' for n, t, _ in secs)
        outline = f'<div class="outline"><h3>سرفصل‌ها</h3><ol>{li}</ol></div>'
    return f'''<section class="opener" id="ch{chno}"><span class="mk">@@C{chno}@@</span>
<div class="band">{art}</div><div class="kicker">فصل</div><div class="no">{fa(chno)}</div>
<h1>{html.escape(meta["title"])}</h1>
<div class="card"><div class="meta">{"".join(chips)}</div>
<div class="goals"><h3>در این فصل یاد می‌گیرید</h3><ul>{goals}</ul></div>{outline}</div></section>'''


def art_svg(seed: int, light: bool = True) -> str:
    """طرح تزئینی منحنی‌های میزان و شبکه (قطعی، بر اساس شماره‌ی فصل)."""
    import math
    import random
    rnd = random.Random(seed)
    cx, cy = rnd.uniform(40, 130), rnd.uniform(20, 70)
    col = "#0f6e6e" if light else "#ffffff"
    paths = []
    for k in range(1, 15):
        r = k * rnd.uniform(5.5, 7.5)
        pts = []
        for a in range(0, 361, 8):
            t = math.radians(a)
            rr = r * (1 + .18 * math.sin(3 * t + seed) + .08 * math.cos(5 * t + k))
            pts.append(f"{cx + rr * math.cos(t) * 1.25:.1f},{cy + rr * math.sin(t):.1f}")
        paths.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{col}" stroke-width="{.25 if k % 4 else .55}" opacity="{.32 if light else .5}"/>')
    hexes = []
    for i in range(14):
        x, y = rnd.uniform(0, 170), rnd.uniform(0, 92)
        s = 3.2
        pts = " ".join(f"{x + s * math.cos(math.radians(60 * j + 30)):.1f},{y + s * math.sin(math.radians(60 * j + 30)):.1f}" for j in range(6))
        hexes.append(f'<polygon points="{pts}" fill="{"#b8741a" if i % 3 == 0 else col}" opacity="{.18 + .05 * (i % 4)}"/>')
    dots = "".join(f'<circle cx="{rnd.uniform(0,170):.1f}" cy="{rnd.uniform(0,92):.1f}" r=".7" fill="{col}" opacity=".6"/>' for _ in range(40))
    return f'<svg viewBox="0 0 170 92" preserveAspectRatio="xMidYMid slice">{"".join(paths)}{"".join(hexes)}{dots}</svg>'


# ---------------------------------------------------------------- مونتاژ
def build_html(book: dict, pages: dict | None = None) -> tuple[str, list]:
    pages = pages or {}
    pg = lambda mk: fa(pages.get(mk, "")) if pages else ""  # noqa: E731
    parts_html, toc, chno = [], [], 0
    for front in book.get("front", []):
        if not (HERE / front).exists():
            continue
        meta, md = parse_md(HERE / front)
        body = pandoc(expand_runs(md))
        mk = f"@@F{Path(front).stem}@@"
        toc.append(("front", meta.get("title", ""), mk, None))
        parts_html.append(f'<section class="front front-chapter"><span class="mk">{mk}</span><h1>{html.escape(meta.get("title",""))}</h1>{body}</section>')
    for pno, part in enumerate(book["parts"], 1):
        chs = [c for c in part["chapters"] if (HERE / c).exists()]
        if not chs:
            continue
        mk = f"@@P{pno}@@"
        toc.append(("part", f'بخش {fa(pno)}: {part["title"]}', mk, None))
        chlist = []
        start = chno
        for c in chs:
            start += 1
            chlist.append(f'<div><span>{fa(start)}</span>{html.escape(parse_md(HERE / c)[0]["title"])}</div>')
        parts_html.append(f'''<section class="part-page"><span class="mk">{mk}</span><div class="art">{art_svg(100 + pno, False)}</div>
<div class="in"><div class="pno">بخش {fa(pno)}</div><h1>{html.escape(part["title"])}</h1>
<div class="pin">{html.escape(part.get("intro", ""))}</div><div class="pch">{"".join(chlist)}</div></div></section>''')
        for c in chs:
            chno += 1
            meta, md = parse_md(HERE / c)
            body, secs = number_body(pandoc(expand_runs(md)), chno, [])
            toc.append(("ch", meta["title"], f"@@C{chno}@@", (chno, secs)))
            parts_html.append(opener(chno, meta, art_svg(chno), secs))
            parts_html.append(f'<section class="chapter-body">{body}</section>')
    for back in book.get("back", []):
        if not (HERE / back).exists():
            continue
        meta, md = parse_md(HERE / back)
        mk = f"@@B{Path(back).stem}@@"
        toc.append(("back", meta.get("title", ""), mk, None))
        parts_html.append(f'<section class="front-chapter back-matter"><span class="mk">{mk}</span>'
                          f'<h1>{html.escape(meta.get("title",""))}</h1>{pandoc(expand_runs(md))}</section>')

    # فهرست مطالب
    items = []
    for kind, title, mk, extra in toc:
        if kind == "part":
            items.append(f'<li class="t-part">{html.escape(title)}</li>')
        elif kind == "ch":
            n, secs = extra
            items.append(f'<li class="t-ch"><span class="n">{fa(n)}</span><span>{html.escape(title)}</span><span class="dots"></span><span class="pg">{pg(mk)}</span></li>')
            for sn, st, smk in secs:
                items.append(f'<li class="t-sec"><span><bdi>{fa(n)}-{fa(sn)}</bdi>&nbsp; <bdi>{html.escape(st)}</bdi></span><span class="dots"></span><span class="pg">{pg(smk)}</span></li>')
        else:
            items.append(f'<li class="t-ch"><span>{html.escape(title)}</span><span class="dots"></span><span class="pg">{pg(mk)}</span></li>')
    toc_html = f'<section class="toc front"><h1>فهرست مطالب</h1><ol>{"".join(items)}</ol></section>'

    title = book["title"]
    tp = f'''<section class="front"><div class="title-page"><h1>{html.escape(title)}</h1>
<div class="sub">{html.escape(book["subtitle"])}</div><div class="rule"></div>
<div class="author">{html.escape(book.get("author", ""))}</div><div class="ed">{html.escape(book.get("edition",""))}</div></div></section>'''
    colo_rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(fa(v))}</td></tr>" for k, v in book.get("colophon", {}).items())
    colo = f'<section class="front colophon"><table>{colo_rows}</table></section>'
    ded = f'<section class="front"><div class="dedication">{book.get("dedication","")}</div></section>' if book.get("dedication") else ""

    doc = f'''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<link rel="stylesheet" href="../assets/book.css"></head><body>
{tp}{colo}{ded}{toc_html}{"".join(parts_html)}</body></html>'''
    return doc, toc


def render_pdf(src: Path, dst: Path) -> None:
    env = {**os.environ, "NODE_PATH": os.environ.get("NODE_PATH") or subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()}
    subprocess.run(["node", str(HERE / "render.js"), str(src), str(dst)], check=True, env=env)


def page_marks(pdf: Path) -> dict:
    text = subprocess.run(["pdftotext", "-raw", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    marks = {}
    for i, page in enumerate(text.split("\f"), 1):
        for mk in re.findall(r"@@[A-Za-z0-9_-]+@@", page):
            marks.setdefault(mk, i)
    return marks


def build_cover(book: dict, pages: int) -> None:
    from cover import cover_html  # noqa: PLC0415
    for kind in ("front", "back", "spread"):
        (OUT / f"cover-{kind}.html").write_text(cover_html(book, kind, pages), encoding="utf-8")
        render_pdf(OUT / f"cover-{kind}.html", OUT / f"cover-{kind}.pdf")


def check(book: dict) -> int:
    errors = 0
    files = book.get("front", []) + [c for p in book["parts"] for c in p["chapters"]] + book.get("back", [])
    for f in files:
        p = HERE / f
        if not p.exists():
            continue
        meta, md = parse_md(p)
        for w in BANNED:
            if w in md or w in json.dumps(meta, ensure_ascii=False):
                print(f"{f}: واژه‌ی ممنوع «{w}»")
                errors += 1
        for img in re.findall(r"!\[[^\]]*\]\(([^)\s]+)", md):
            if not (OUT / img).exists() and not (HERE / img.removeprefix("../")).exists():
                print(f"{f}: تصویر پیدا نشد {img}")
                errors += 1
        for m in RUN_RE.finditer(md):
            try:
                os.environ["BOOK_RERUN"] = "1"
                lim = re.search(r"rows=(\d+)", m.group("attrs"))
                run_sql(m.group("sql"), int(lim.group(1)) if lim else 6)
            except Exception as e:  # noqa: BLE001
                print(f"{f}: SQL خطا داد: {str(e).splitlines()[0]}\n    {m.group('sql')[:120]}")
                errors += 1
    print("بدون خطا" if not errors else f"{errors} خطا")
    return errors


def main() -> None:
    sys.path.insert(0, str(HERE))
    book = load()
    OUT.mkdir(exist_ok=True)
    if "--check" in sys.argv:
        raise SystemExit(1 if check(book) else 0)
    doc, _ = build_html(book)
    (OUT / "book.html").write_text(doc, encoding="utf-8")
    for f in RES.glob("*.json"):  # نتیجه‌ی کدهایی که دیگر در کتاب نیستند
        if f.stem not in USED:
            f.unlink()
    if "--html" in sys.argv:
        print(OUT / "book.html")
        return
    render_pdf(OUT / "book.html", OUT / "body.pdf")          # گذر اول: یافتن شماره‌ی صفحه‌ها
    marks = page_marks(OUT / "body.pdf")
    doc, _ = build_html(book, marks)
    (OUT / "book.html").write_text(doc, encoding="utf-8")
    render_pdf(OUT / "book.html", OUT / "body.pdf")          # گذر دوم: فهرست با شماره‌ی صفحه
    marks2 = page_marks(OUT / "body.pdf")
    if marks2 != marks:                                       # اگر طول فهرست صفحه‌ها را جابه‌جا کرد
        doc, _ = build_html(book, marks2)
        (OUT / "book.html").write_text(doc, encoding="utf-8")
        render_pdf(OUT / "book.html", OUT / "body.pdf")
    n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(OUT / "body.pdf")], capture_output=True, text=True).stdout).group(1))
    build_cover(book, n)
    subprocess.run(["pdfunite", str(OUT / "cover-front.pdf"), str(OUT / "body.pdf"), str(OUT / "cover-back.pdf"), str(OUT / "book.pdf")], check=True)
    print(f"{OUT / 'book.pdf'}  ({n} صفحه‌ی متن + جلد)\n{OUT / 'cover-spread.pdf'}  (جلد کامل برای چاپخانه)")


if __name__ == "__main__":
    main()
