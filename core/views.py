import datetime
import os
from xml.sax.saxutils import escape

from django.conf import settings
from django.db import connection
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse

from databases.models import Extension, Plan

DOCS = [
    ("what-is-postgis", "پایگاه داده مکانی و PostGIS چیست؟",
     "راهنمای کامل پایگاه داده مکانی: کاربردها، توابع مکانی، مقایسه با Shapefile و شروع رایگان"),
    ("start", "شروع سریع در ۳ دقیقه", "ساخت حساب، ساخت پایگاه داده و گرفتن رشته اتصال"),
    ("qgis", "اتصال از QGIS", "افزودن اتصال PostGIS در QGIS و نمایش لایه‌ها"),
    ("import", "وارد کردن Shapefile و GeoPackage", "سه روش: DB Manager در QGIS، ogr2ogr و shp2pgsql"),
    ("geoserver", "اتصال به GeoServer", "ساخت Store از نوع PostGIS و انتشار لایه WMS/WFS"),
    ("code", "اتصال از Python و Node.js", "نمونه کد با psycopg، GeoPandas و node-postgres"),
    ("srid", "سیستم مختصات و SRID در ایران", "انتخاب SRID درست: 4326، 3857 و UTM ایران"),
    ("sql", "کوئری‌های مکانی پرکاربرد", "بافر، فاصله، تقاطع، نمایه مکانی و چند مثال واقعی"),
    ("limits", "محدودیت‌ها و قوانین پلن رایگان", "حجم، اتصال، زمان کوئری، انقضا و بکاپ"),
]
DOC_SLUGS = {d[0] for d in DOCS}


def home(request):
    plans = Plan.objects.filter(is_public=True)
    exts = Extension.objects.filter(is_active=True)
    return render(request, "core/home.html", {"plans": plans, "extensions": exts})


def docs_index(request):
    return render(request, "docs/index.html", {"docs": DOCS})


def docs_page(request, slug):
    if slug not in DOC_SLUGS:
        raise Http404
    idx = [d[0] for d in DOCS].index(slug)
    ctx = {
        "doc": DOCS[idx],
        "docs": DOCS,
        "prev": DOCS[idx - 1] if idx > 0 else None,
        "next": DOCS[idx + 1] if idx < len(DOCS) - 1 else None,
        "plan": Plan.objects.filter(is_default=True).first(),
    }
    return render(request, f"docs/{slug}.html", ctx)


def terms(request):
    return render(request, "core/terms.html")


def healthz(request):
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        return JsonResponse({"status": "ok"})
    except Exception:  # noqa: BLE001
        return JsonResponse({"status": "db-error"}, status=503)


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /manage/",
        "Disallow: /dashboard/",
        "Disallow: /accounts/",
        "Disallow: /billing/",
        "Disallow: /support/",
        "",
        f"Sitemap: {settings.CANONICAL_URL}/sitemap.xml",
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")


def _template_date(name: str) -> str:
    from django.template.loader import get_template

    try:
        path = get_template(name).origin.name
        return datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()
    except Exception:  # noqa: BLE001
        return datetime.date.today().isoformat()


def sitemap_xml(request):
    base = settings.CANONICAL_URL
    pages = [(reverse("core:home"), "1.0", "core/home.html"),
             (reverse("core:docs"), "0.8", "docs/index.html")]
    pages += [(reverse("core:doc", args=[d[0]]), "0.9" if d[0] == "what-is-postgis" else "0.7", f"docs/{d[0]}.html")
              for d in DOCS]
    pages.append((reverse("core:terms"), "0.3", "core/terms.html"))
    items = "".join(
        f"<url><loc>{escape(base + path)}</loc><lastmod>{_template_date(tpl)}</lastmod>"
        f"<priority>{prio}</priority></url>"
        for path, prio, tpl in pages)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>')
    return HttpResponse(xml, content_type="application/xml; charset=utf-8")
