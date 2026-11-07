"""ساخت صفحه‌های HTML سایت از قالب مشترک: python3 pgpro-site/tools/build_pages.py (خروجی در pgpro-site/public)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import pages_home  # noqa: E402
import pages_other  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "public"
PAGES = {"index.html": pages_home.build, "setup.html": pages_other.setup, "specs.html": pages_other.specs,
         "download.html": pages_other.download, "order.html": pages_other.order, "404.html": pages_other.not_found}

if __name__ == "__main__":
    for name, fn in PAGES.items():
        (OUT / name).write_text(fn(), encoding="utf-8")
        print("ساخته شد:", name)
