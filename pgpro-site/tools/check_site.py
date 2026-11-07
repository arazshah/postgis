"""بررسی سایت استاتیک: لینک‌ها و فایل‌های داخلی، تعادل صفحه‌ها با build_pages، نبودن style/script درون‌خطی (CSP)."""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "public"
bad = []
pages = {p.name: p.read_text(encoding="utf-8") for p in ROOT.glob("*.html")}
ids = {n: set(re.findall(r'\sid="([^"]+)"', t)) for n, t in pages.items()}


def target(path: str) -> str | None:
    if path in ("", "/"):
        return "index.html"
    name = path.strip("/")
    return f"{name}.html" if f"{name}.html" in pages else None


for name, text in pages.items():
    if re.search(r'\sstyle="', text) or re.search(r"<script(?![^>]*(src=|application/ld\+json))", text):
        bad.append(f"{name}: style/script درون‌خطی (CSP آن را می‌بندد)")
    for url in re.findall(r'\s(?:href|src)="([^"]+)"', text):
        if re.match(r"(https?:|mailto:|tel:|data:)", url):
            continue
        path, _, frag = url.partition("#")
        if path.startswith("/assets/") or path in ("/favicon.svg", "/robots.txt", "/sitemap.xml"):
            if not (ROOT / path.lstrip("/")).exists():
                bad.append(f"{name}: فایل نیست {url}")
            continue
        if path.startswith("/update"):
            continue
        t = target(path.split("?")[0]) if path else name
        if t is None:
            bad.append(f"{name}: لینک شکسته {url}")
        elif frag and frag not in ids[t]:
            bad.append(f"{name}: لنگر نیست {url}")

sitemap = (ROOT / "sitemap.xml").read_text()
for name in pages:
    if name not in ("404.html", "index.html") and f"/{name[:-5]}<" not in sitemap:
        bad.append(f"sitemap.xml بدون {name}")

print("\n".join(bad) or f"سالم: {len(pages)} صفحه")
sys.exit(1 if bad else 0)
