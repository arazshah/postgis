from django.db import connection
from django.http import Http404, JsonResponse
from django.shortcuts import render

from databases.models import Extension, Plan

DOCS = [
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
