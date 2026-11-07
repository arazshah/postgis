"""قالب مشترک صفحه‌های pgpro.ir: سربرگ، پا و تابع ساخت صفحه. محتوای هر صفحه در pages_*.py است."""
import html

SITE = "https://pgpro.ir"
NAME = "پایگاه داده مکانی پرو"
ENDPOINT = "https://postgis.ir/api/pgpro/lead/"
FALLBACK = "https://postgis.ir/contact/?topic=pgpro"
VERSION = "0.1.0"

NAV = [("/", "خانه"), ("/setup", "راهنمای راه‌اندازی"), ("/specs", "مشخصات"), ("/download", "نسخه‌ها و به‌روزرسانی"), ("/order", "سفارش")]


def icon(name, cls=""):
    return f'<svg class="i {cls}" aria-hidden="true"><use href="/assets/icons.svg#i-{name}"/></svg>'


def head(title, desc, path, extra=""):
    full = f"{title} — {NAME}" if path != "/" else title
    url = SITE + (path if path != "/" else "/")
    return f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(full)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{url}">
<meta name="theme-color" content="#0F5C59">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<meta property="og:type" content="website"><meta property="og:locale" content="fa_IR">
<meta property="og:site_name" content="{NAME}">
<meta property="og:title" content="{html.escape(full)}"><meta property="og:description" content="{html.escape(desc)}">
<meta property="og:url" content="{url}"><meta property="og:image" content="{SITE}/assets/img/og.jpg">
<meta name="twitter:card" content="summary_large_image">
<link rel="preload" href="/assets/fonts/vazirmatn-arabic-400-normal.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/assets/css/site.css">
{extra}</head>
"""


def header(path):
    links = "".join(
        f'<a href="{h}"{" aria-current=\"page\"" if h == path else ""}>{t}</a>' for h, t in NAV)
    return f"""<body>
<a class="skip" href="#main">پرش به محتوا</a>
<header class="top"><div class="wrap">
<a class="brand" href="/"><img src="/assets/img/logo.svg" alt="" width="38" height="38"><span>{NAME}<small>PostGIS&nbsp;Pro</small></span></a>
<nav class="nav" id="nav" aria-label="منوی اصلی">{links}</nav>
<span class="gap"></span>
<a class="btn btn-sm" href="/order">{icon("mail", "s")}<span>درخواست پیش‌فاکتور</span></a>
<button class="menu-btn" type="button" aria-label="منو" aria-expanded="false" aria-controls="nav">{icon("more")}</button>
</div></header>
<main id="main">
"""


def footer():
    return f"""</main>
<footer class="foot"><div class="wrap">
<div class="foot-grid">
<div><a class="brand" href="/"><img src="/assets/img/logo.svg" alt="" width="38" height="38"><span>{NAME}</span></a>
<p>نسخه‌ی آفلاین و روی‌دستگاه سرویس <a href="https://postgis.ir">ژئوپایگاه (postgis.ir)</a>؛ پایگاه داده مکانی PostGIS برای سازمان‌هایی که داده باید در شبکه‌ی خودشان بماند.</p></div>
<div><h4>محصول</h4><ul><li><a href="/#features">امکانات</a></li><li><a href="/#offline-map">نقشه‌ی آفلاین ایران</a></li><li><a href="/specs">مشخصات فنی</a></li><li><a href="/#faq">پرسش‌های متداول</a></li></ul></div>
<div><h4>راهنما</h4><ul><li><a href="/setup">راه‌اندازی در ۵ دقیقه</a></li><li><a href="/setup#qgis">اتصال QGIS</a></li><li><a href="/download">نسخه‌ها و به‌روزرسانی</a></li><li><a href="/setup#reset">فراموشی رمز</a></li></ul></div>
<div><h4>ارتباط</h4><ul><li><a href="/order">درخواست پیش‌فاکتور</a></li><li><a href="/order?interest=trial">نسخه‌ی آزمایشی</a></li><li><a href="https://postgis.ir">postgis.ir (نسخه‌ی ابری)</a></li><li><a href="https://postgis.ir/privacy/">حریم خصوصی</a></li></ul></div>
</div>
<div class="copy"><span>© ۱۴۰۵ ژئوپایگاه · pgpro.ir</span><span class="ltr">v{VERSION}</span></div>
</div></footer>
<script src="/assets/js/site.js" defer></script>
</body>
</html>
"""


def page(path, title, desc, body, extra_head="", banner=True):
    status = ""
    if banner:
        status = f"""<div class="status"><div class="wrap">{icon("info", "s")}<span>پیش‌فروش و نسخه‌ی آزمایشی باز است.</span><a href="/order?interest=trial">نسخه‌ی آزمایشی بگیرید</a></div></div>
"""
    return head(title, desc, path, extra_head) + header(path) + status + body + footer()
