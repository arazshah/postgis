#!/usr/bin/env python3
"""نسخه‌ی Word (docx) کتاب برای ویرایش: python docs/book/build_docx.py  →  out/book.docx

همان منبع نسخه‌ی چاپی (book.json و chapters/*.md) و همان نتیجه‌های اجراشده‌ی SQL (results/).
پیش‌نیاز: pandoc، python-docx، و یک بار ساخت PDF (برای تصویر جلد: out/cover-*.pdf) و svg2png.js (نمودارها).
"""
from __future__ import annotations

import copy
import re
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402

OUT = HERE / "out" / "docx"
FIG = OUT / "fig"
FA = build.fa
BODY_FONT, HEAD_FONT, MONO_FONT = "Vazirmatn", "Vazirmatn", "Consolas"
TEAL, OCHRE = RGBColor(0x0A, 0x4F, 0x50), RGBColor(0xB8, 0x74, 0x1A)

BOXES = {  # کلاس کادر ← (برچسب، نام سبک Word، رنگ زمینه)
    "note": ("نکته", "Box Note", "E3F1EF"), "warn": ("هشدار", "Box Warning", "FBEAEA"),
    "know": ("بدانید", "Box Know", "FBF1E1"), "pro": ("سطح حرفه‌ای", "Box Pro", "EFECF8"),
    "real": ("در دنیای واقعی", "Box Real", "E6F3EB"), "try": ("خودتان امتحان کنید", "Box Try", "F3F5F5"),
    "teach": ("برای مدرس", "Box Teach", "FFF8EC"), "summary": ("خلاصه‌ی فصل", "Box Summary", "F3F5F5"),
}


# ---------------------------------------------------------------- Markdown برای pandoc
def md_table(res: dict) -> str:
    if not res["cols"]:
        return f"\n::: {{custom-style=\"SQL Result\"}}\n{res['msg']}\n:::\n"
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    lines = ["| " + " | ".join(esc(c) for c in res["cols"]) + " |", "|" + "---|" * len(res["cols"])]
    lines += ["| " + " | ".join(esc(v) for v in r) + " |" for r in res["rows"]]
    if res["total"] > len(res["rows"]):
        lines.append("| " + " | ".join([f"… ({res['total']} rows)"] + [""] * (len(res["cols"]) - 1)) + " |")
    return "\n\n: نتیجه‌ی اجرا {.sqlresult}\n\n" + "\n".join(lines) + "\n"


def expand_runs(md: str) -> str:
    def rep(m):
        attrs, sql = m.group("attrs"), m.group("sql")
        lim = re.search(r"rows=(\d+)", attrs)
        res = build.run_sql(build.with_setup(attrs, sql), int(lim.group(1)) if lim else 6)
        return f"```sql\n{sql}\n```\n{md_table(res)}"
    return build.RUN_RE.sub(rep, md)


def transform(md: str, chno: int | None, shift: int) -> str:
    md = expand_runs(md)
    # تصویرها: مسیر مطلق، پهنای مناسب، شماره‌ی شکل
    fig = [0]

    def img(m):
        cap, src, attrs = m.group(1), m.group(2), m.group(3) or ""
        if src.startswith("../figures/"):
            path = FIG / Path(src).with_suffix(".png").name
        else:
            path = HERE / src.removeprefix("../")
        width = "6.5cm" if "phone" in attrs else "13.4cm"
        if chno is not None and cap:
            fig[0] += 1
            cap = f"شکل {FA(chno)}-{FA(fig[0])}: {cap}"
        return f"![{cap}]({path}){{width={width}}}"
    md = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)(\{[^}]*\})?", img, md)
    # شماره‌ی بخش‌ها و پایین بردن سطح سرعنوان‌ها
    sec = [0]

    def head(m):
        level = len(m.group(1))
        text = m.group(2)
        if level == 2 and chno is not None:
            sec[0] += 1
            text = f"{FA(chno)}-{FA(sec[0])} {text}"
        return "#" * min(level + shift, 6) + " " + text
    md = re.sub(r"^(#{2,5}) (.+)$", head, md, flags=re.M)
    # کادرها و بلوک‌های ویژه
    out, stack = [], []
    for line in md.split("\n"):
        m = re.match(r"^:::\s*(\w+)\s*$", line)
        if m and m.group(1) in BOXES:
            label, style, _ = BOXES[m.group(1)]
            out += [f'::: {{custom-style="{style}"}}', f"**{label}**", ""]
            stack.append("box")
        elif m and m.group(1) in ("steps", "exercises", "gloss"):
            stack.append("plain")
        elif line.strip() == ":::" and stack:
            if stack.pop() == "box":
                out.append(":::")
        else:
            out.append(line)
    md = "\n".join(out)
    md = re.sub(r"\[([^\]]+)\]\{\.badge[^}]*\}", r"[\1]", md)   # برچسب سطح تمرین
    return md


def chapter_header(chno: int, meta: dict) -> str:
    lvl = int(meta.get("level", 1))
    parts = [f"سطح: **{build.LEVELS[lvl]}**"]
    if meta.get("time"):
        parts.append(f"زمان مطالعه: **{FA(meta['time'])}**")
    if meta.get("prereq"):
        parts.append(f"پیش‌نیاز: **{FA(meta['prereq'])}**")
    goals = "\n".join(f"- {g if isinstance(g, str) else '; '.join(f'{k}: {v}' for k, v in g.items())}" for g in meta.get("goals", []))
    return (f"## فصل {FA(chno)}: {meta['title']}\n\n::: {{custom-style=\"Chapter Meta\"}}\n{' · '.join(parts)}\n:::\n\n"
            f"::: {{custom-style=\"Box Goals\"}}\n**در این فصل یاد می‌گیرید**\n\n{goals}\n:::\n")


def assemble(book: dict) -> str:
    md = ["---\nlang: fa\ndir: rtl\n---\n",
          "::: {custom-style=\"Cover\"}\n![](COVER_FRONT)\n:::\n"]
    colo = "\n".join(f"| {k} | {FA(v)} |" for k, v in book.get("colophon", {}).items())
    md.append(f"\n## شناسنامه‌ی کتاب {{.unnumbered}}\n\n| | |\n|---|---|\n{colo}\n")
    md.append("\n## فهرست مطالب {.unnumbered}\n\nTOC_PLACEHOLDER\n")
    for f in book.get("front", []):
        meta, body = build.parse_md(HERE / f)
        md.append(f"\n## {meta['title']} {{.unnumbered}}\n\n{transform(body, None, 1)}\n")
    for pno, part in enumerate(book["parts"], 1):
        chs = [c for c in part["chapters"] if (HERE / c).exists()]
        if not chs:
            continue
        md.append(f"\n# بخش {FA(pno)}: {part['title']}\n\n::: {{custom-style=\"Part Intro\"}}\n{part.get('intro', '')}\n:::\n")
        for c in chs:
            chno = build.chapter_no(c)
            meta, body = build.parse_md(HERE / c)
            md.append("\n" + chapter_header(chno, meta) + "\n" + transform(body, chno, 1) + "\n")
    md.append("\n# پیوست‌ها\n")
    for f in book.get("back", []):
        meta, body = build.parse_md(HERE / f)
        md.append(f"\n## {meta['title']}\n\n{transform(body, None, 1)}\n")
    md.append("\n::: {custom-style=\"Cover\"}\n![](COVER_BACK)\n:::\n")
    return "\n".join(md)


# ---------------------------------------------------------------- سند مرجع (سبک‌ها و صفحه)
def set_font(style, name: str, size: float | None = None, bold: bool | None = None, color=None):
    style.font.name = name
    rpr = style.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.append(fonts)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(a), name)
    for tag in ("w:sz", "w:szCs"):
        if size:
            el = rpr.find(qn(tag))
            el = OxmlElement(tag) if el is None else el
            el.set(qn("w:val"), str(int(size * 2)))
            if el.getparent() is None:
                rpr.append(el)
    if bold is not None:
        style.font.bold = bold
        for tag in ("w:bCs",):
            el = OxmlElement(tag)
            if not bold:
                el.set(qn("w:val"), "0")
            rpr.append(el)
    if color is not None:
        style.font.color.rgb = color


def ppr_set(style, *, bidi: bool | None = None, jc: str | None = None, shading: str | None = None,
            border: str | None = None, before: int | None = None, after: int | None = None, keep_next: bool = False):
    ppr = style.element.get_or_add_pPr()
    if bidi is not None:
        el = ppr.find(qn("w:bidi"))
        if el is None:
            el = OxmlElement("w:bidi")
            ppr.append(el)
        el.set(qn("w:val"), "1" if bidi else "0")
    if shading:
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), shading)
        ppr.append(shd)
    if border:
        pbdr = OxmlElement("w:pBdr")
        for side in ("top", "bottom", "left", "right"):
            b = OxmlElement(f"w:{side}")
            b.set(qn("w:val"), "single")
            b.set(qn("w:sz"), "6")
            b.set(qn("w:space"), "4")
            b.set(qn("w:color"), border)
            pbdr.append(b)
        ppr.append(pbdr)
    if before is not None or after is not None:
        sp = OxmlElement("w:spacing")
        if before is not None:
            sp.set(qn("w:before"), str(before))
        if after is not None:
            sp.set(qn("w:after"), str(after))
        ppr.append(sp)
    if keep_next:
        ppr.append(OxmlElement("w:keepNext"))
    if jc:
        el = OxmlElement("w:jc")
        el.set(qn("w:val"), jc)
        ppr.append(el)


def make_reference(path: Path) -> None:
    with open(path, "wb") as fh:
        subprocess.run(["pandoc", "--print-default-data-file", "reference.docx"], stdout=fh, check=True)
    doc = Document(str(path))
    from docx.enum.style import WD_STYLE_TYPE
    real = doc.styles
    if "Source Code" not in [x.name for x in real]:
        real.add_style("Source Code", WD_STYLE_TYPE.PARAGRAPH)

    class _S:  # جست‌وجوی سبک با نام واقعی (python-docx «Heading 1» را به نام دیگری نگاشت می‌کند)
        def __getitem__(self, name):
            return next(x for x in real if x.name == name)

        def add_style(self, *a):
            return real.add_style(*a)

        def __iter__(self):
            return iter(real)
    st = _S()
    for name in ("Normal", "Body Text", "First Paragraph", "Compact", "Block Text"):
        if name in [s.name for s in st]:
            set_font(st[name], BODY_FONT, 11)
            ppr_set(st[name], bidi=True)
    st["Body Text"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    st["Body Text"].paragraph_format.line_spacing = 1.35
    for name, size, color in (("Title", 26, TEAL), ("Subtitle", 14, OCHRE), ("Heading 1", 22, TEAL), ("Heading 2", 18, TEAL),
                              ("Heading 3", 14, TEAL), ("Heading 4", 12, RGBColor(0x1D, 0x2A, 0x2C)), ("Heading 5", 11, TEAL)):
        set_font(st[name], HEAD_FONT, size, True, color)
        ppr_set(st[name], bidi=True)
    st["Heading 1"].paragraph_format.page_break_before = True
    st["Heading 2"].paragraph_format.page_break_before = True
    for name in ("Source Code",):
        set_font(st[name], MONO_FONT, 9)
        ppr_set(st[name], bidi=False, jc="left", shading="F6F8F7", border="C9D2D2")
    if "Verbatim Char" in [s.name for s in st]:
        set_font(st["Verbatim Char"], MONO_FONT, 9.5)
    set_font(st["Caption"], BODY_FONT, 9.5, False, RGBColor(0x4A, 0x57, 0x59))
    ppr_set(st["Caption"], bidi=True, jc="center")
    # سبک‌های تازه
    for key, (_, sname, fill) in BOXES.items():
        s = st.add_style(sname, WD_STYLE_TYPE.PARAGRAPH)
        s.base_style = st["Body Text"]
        ppr_set(s, bidi=True, shading=fill, border="B8741A" if key == "teach" else fill, before=40, after=40)
    for sname, fill in (("Box Goals", "E3F1EF"), ("Part Intro", None), ("Chapter Meta", None), ("SQL Result", "FFFFFF"), ("Cover", None)):
        s = st.add_style(sname, WD_STYLE_TYPE.PARAGRAPH)
        s.base_style = st["Body Text"]
        ppr_set(s, bidi=sname not in ("SQL Result",), shading=fill, border="0F6E6E" if sname == "Box Goals" else None,
                jc="center" if sname == "Cover" else None)
    set_font(st["Part Intro"], BODY_FONT, 12, False, RGBColor(0x4A, 0x57, 0x59))
    set_font(st["Chapter Meta"], BODY_FONT, 10, False, OCHRE)
    set_font(st["SQL Result"], MONO_FONT, 8.5)
    # صفحه: قطع وزیری
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(17), Cm(24)
    sec.left_margin = sec.right_margin = Cm(1.8)
    sec.top_margin = sec.bottom_margin = Cm(2)
    doc.save(str(path))


# ---------------------------------------------------------------- پس‌پردازش
def add_page_number(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)


def finish(path: Path) -> None:
    doc = Document(str(path))
    body = doc.element.body
    # جدول‌ها: نتیجه‌ی SQL چپ‌به‌راست و ثابت‌عرض؛ بقیه راست‌به‌چپ؛ همه با خط
    for t in doc.tables:
        tblpr = t._tbl.tblPr
        cap = tblpr.find(qn("w:tblCaption"))
        is_result = cap is not None and "نتیجه" in (cap.get(qn("w:val")) or "")
        bidi = OxmlElement("w:bidiVisual")
        if is_result:
            bidi.set(qn("w:val"), "0")
        tblpr.append(bidi)
        borders = OxmlElement("w:tblBorders")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            b = OxmlElement(f"w:{side}")
            b.set(qn("w:val"), "single")
            b.set(qn("w:sz"), "4")
            b.set(qn("w:color"), "C9D2D2")
            borders.append(b)
        tblpr.append(borders)
        for i, row in enumerate(t.rows):
            for c in row.cells:
                if i == 0:
                    shd = OxmlElement("w:shd")
                    shd.set(qn("w:val"), "clear")
                    shd.set(qn("w:fill"), "E3F1EF")
                    c._tc.get_or_add_tcPr().append(shd)
                for p in c.paragraphs:
                    ppr = p._p.get_or_add_pPr()
                    el = OxmlElement("w:bidi")
                    el.set(qn("w:val"), "0" if is_result else "1")
                    ppr.insert(0, el)
                    p.alignment = WD_ALIGN_PARAGRAPH.LEFT if is_result else WD_ALIGN_PARAGRAPH.RIGHT
                    for r in p.runs:
                        r.font.size = Pt(8 if is_result else 9)
    # فهرست مطالب: فیلد TOC که Word هنگام باز شدن به‌روز می‌کند
    for p in doc.paragraphs:
        if p.text.strip() == "TOC_PLACEHOLDER":
            for r in p.runs:
                r.text = ""
            run = p.add_run()
            parts = [("begin", None), (None, 'TOC \\o "1-2" \\h \\z \\u'), ("separate", None), ("end", None)]
            for kind, text in parts:
                if kind:
                    el = OxmlElement("w:fldChar")
                    el.set(qn("w:fldCharType"), kind)
                else:
                    el = OxmlElement("w:instrText")
                    el.set(qn("xml:space"), "preserve")
                    el.text = text
                run._r.append(el)
            break
    upd = OxmlElement("w:updateFields")
    upd.set(qn("w:val"), "true")
    doc.settings.element.append(upd)
    # کد: چپ‌به‌راست
    for p in doc.paragraphs:
        if p.style.name in ("Source Code", "SQL Result"):
            ppr = p._p.get_or_add_pPr()
            for el in ppr.findall(qn("w:bidi")):
                ppr.remove(el)
            el = OxmlElement("w:bidi")
            el.set(qn("w:val"), "0")
            ppr.insert(0, el)
    # جلدها: هر کدام در بخش جداگانه‌ی بی‌حاشیه
    covers = [p for p in doc.paragraphs if p.style.name == "Cover"]
    final = body.sectPr
    if len(covers) == 2:
        front, back = covers
        sp = copy.deepcopy(final)               # پایان بخش جلد رو: بی‌حاشیه
        sp.find(qn("w:pgMar")).attrib.update({qn(k): "0" for k in ("w:top", "w:bottom", "w:left", "w:right", "w:header", "w:footer")})
        front._p.get_or_add_pPr().append(sp)
        prev = back._p.getprevious()            # پایان متن: حاشیه‌ی عادی، با شماره‌ی صفحه
        holder = OxmlElement("w:p")
        holder_ppr = OxmlElement("w:pPr")
        holder_ppr.append(copy.deepcopy(final))
        holder.append(holder_ppr)
        prev.addnext(holder)
        final.find(qn("w:pgMar")).attrib.update({qn(k): "0" for k in ("w:top", "w:bottom", "w:left", "w:right", "w:header", "w:footer")})
        for p in covers:
            p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(0)
            for r in p.runs:
                for ext in r._r.iter(qn("wp:extent")):
                    ext.set("cx", str(Cm(16.9)))
                    ext.set("cy", str(Cm(23.85)))
                for ext in r._r.iter(qn("a:ext")):
                    ext.set("cx", str(Cm(16.9)))
                    ext.set("cy", str(Cm(23.85)))
    doc.save(str(path))
    doc = Document(str(path))
    if len(doc.sections) >= 2:
        body_sec = doc.sections[1]
        body_sec.footer.is_linked_to_previous = False
        add_page_number(body_sec)
    if len(doc.sections) >= 3:                 # جلد پشت بدون شماره‌ی صفحه
        last = doc.sections[-1]
        last.footer.is_linked_to_previous = False
        for p in last.footer.paragraphs:
            for r in p.runs:
                r._r.getparent().remove(r._r)
    doc.save(str(path))


def main() -> None:
    book = build.load()
    OUT.mkdir(parents=True, exist_ok=True)
    if not FIG.exists() or not any(FIG.iterdir()):
        subprocess.run(["node", str(HERE / "svg2png.js"), str(FIG)], check=True)
    for kind in ("front", "back"):
        pdf = HERE / "out" / f"cover-{kind}.pdf"
        subprocess.run(["pdftoppm", "-r", "220", "-png", "-singlefile", str(pdf), str(OUT / f"cover-{kind}")], check=True)
    md = assemble(book).replace("COVER_FRONT", str(OUT / "cover-front.png")).replace("COVER_BACK", str(OUT / "cover-back.png"))
    (OUT / "book.md").write_text(md, encoding="utf-8")
    ref = OUT / "reference.docx"
    make_reference(ref)
    dst = HERE / "out" / "book.docx"
    subprocess.run(["pandoc", str(OUT / "book.md"), "-f", "markdown+fenced_divs+bracketed_spans+pipe_tables+implicit_figures+raw_html",
                    "-o", str(dst), "--reference-doc", str(ref), "--highlight-style=pygments"], check=True)
    finish(dst)
    print(dst)


if __name__ == "__main__":
    main()
