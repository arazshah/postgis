"""تکه‌بندی مقاله برای بازیابی معنایی (RAG).

هر تکه یک بخش مستقل از مقاله با سرفصل و لنگر خودش است، تا دستیار بتواند همان بخش را با پیوند دقیق نقل کند.
تکه‌ها متن خام (با توکن‌ها) را نگه می‌دارند؛ مقدارهای پلن هنگام خواندن با tokens.resolve جایگزین می‌شوند.
"""
from __future__ import annotations

import hashlib
import re

from . import text as fa

MIN_CHARS = 280
MAX_CHARS = 1400
_HEAD = re.compile(r"^(#{2,3})\s+(.+?)\s*#*\s*$")


def _sections(body: str):
    """[(سرفصل یا None, لنگر، متن)] به ترتیب؛ سرفصل داخل بلوک کد نادیده گرفته می‌شود."""
    _, heads = fa.render_markdown(body)
    head_iter = iter(heads)
    out, cur_title, cur_anchor, buf, in_code = [], None, "", [], False
    for line in (body or "").splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        m = None if in_code else _HEAD.match(line)
        if m:
            out.append((cur_title, cur_anchor, "\n".join(buf).strip()))
            nxt = next(head_iter, None)
            cur_title, cur_anchor, buf = m.group(2).strip(), (nxt[2] if nxt else ""), []
        else:
            buf.append(line)
    out.append((cur_title, cur_anchor, "\n".join(buf).strip()))
    return [s for s in out if s[2] or s[0]]


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    parts, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        if cur and len(cur) + len(para) > MAX_CHARS:
            parts.append(cur.strip())
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        parts.append(cur.strip())
    return parts


def build_chunks(title: str, summary: str, body: str) -> list[dict]:
    """[{ordinal, heading, anchor, text}]؛ تکه ۰ همیشه عنوان + پاسخ کوتاه (+ مقدمه) است."""
    sections = _sections(body)
    chunks: list[dict] = []
    intro = ""
    if sections and sections[0][0] is None:
        intro = sections.pop(0)[2]
    chunks.append({"heading": title, "anchor": "", "text": "\n\n".join(x for x in (summary.strip(), intro) if x)})

    pending: dict | None = None
    for heading, anchor, text in sections:
        for piece in _split_long(text) or [""]:
            item = {"heading": heading or title, "anchor": anchor, "text": piece}
            if pending is not None:
                if len(pending["text"]) < MIN_CHARS and len(pending["text"]) + len(piece) <= MAX_CHARS:
                    item = {"heading": f'{pending["heading"]} / {item["heading"]}', "anchor": pending["anchor"],
                            "text": f'**{pending["heading"]}**\n{pending["text"]}\n\n**{item["heading"]}**\n{piece}'}
                else:
                    chunks.append(pending)
            pending = item
    if pending is not None:
        chunks.append(pending)

    for i, c in enumerate(chunks):
        c["ordinal"] = i
        c["text"] = c["text"].strip()
    return [c for c in chunks if c["text"]] or chunks[:1]


def rebuild_chunks(article) -> int:
    from .models import ArticleChunk

    rows = build_chunks(article.title, article.summary, article.body)
    existing = {c.ordinal: c.text_hash for c in article.chunks.all()}
    wanted = {r["ordinal"]: hashlib.sha256(f'{r["heading"]}\n{r["text"]}'.encode()).hexdigest() for r in rows}
    if existing == wanted:
        return 0
    article.chunks.all().delete()
    ArticleChunk.objects.bulk_create([
        ArticleChunk(article=article, ordinal=r["ordinal"], heading=r["heading"][:300], anchor=r["anchor"][:300],
                     text=r["text"], text_hash=wanted[r["ordinal"]]) for r in rows])
    return len(rows)
