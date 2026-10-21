"""پرسش‌های متداول صفحه اصلی: از مقاله‌های ویژه (featured) پایگاه دانش خوانده می‌شود."""
from __future__ import annotations

import json

from django.utils.safestring import mark_safe

from . import text as fa
from . import tokens
from .models import Article

HOME_LIMIT = 8

# اگر هنوز هیچ مقاله ویژه‌ای ساخته نشده باشد (پایگاه داده تازه)، همین‌ها نمایش داده می‌شود
FALLBACK = [
    {"title": "پایگاه داده مکانی چیست؟", "url": "",
     "summary": "پایگاه داده‌ای که علاوه بر متن و عدد، نقطه، خط و چندضلعی را ذخیره می‌کند و با توابع مکانی مثل فاصله، تقاطع و بافر روی آن‌ها تحلیل انجام می‌دهد. PostGIS محبوب‌ترین پایگاه داده مکانی متن‌باز است."},
    {"title": "آیا برای استفاده باید PostgreSQL یا PostGIS نصب کنم؟", "url": "",
     "summary": "نه. پایگاه داده روی سرور ما ساخته می‌شود و شما فقط اطلاعات اتصال را در QGIS، GeoServer یا کد خود وارد می‌کنید."},
    {"title": "آیا اتصال امن است؟", "url": "",
     "summary": "بله. اتصال با SSL رمزنگاری می‌شود، هر پایگاه داده کاربر جداگانه دارد و کاربران به پایگاه داده یکدیگر دسترسی ندارند."},
    {"title": "با چه نرم‌افزارهایی می‌توانم وصل شوم؟", "url": "",
     "summary": "هر ابزاری که با PostgreSQL کار می‌کند: QGIS، ArcGIS Pro، GeoServer، پایتون (GeoPandas، psycopg)، GeoDjango، Node.js، ogr2ogr و psql."},
]


def home_faqs() -> list[dict]:
    arts = list(Article.objects.filter(
        is_featured=True, status=Article.Status.PUBLISHED, audience=Article.Audience.PUBLIC,
        category__is_active=True)[:HOME_LIMIT])
    if not arts:
        return FALLBACK
    vals = tokens.values()
    return [{"title": a.title, "summary": fa.plain_text(tokens.resolve(a.summary, vals)),
             "url": a.get_absolute_url()} for a in arts]


def faq_jsonld(faqs: list[dict]):
    data = [{"@type": "Question", "name": f["title"],
             "acceptedAnswer": {"@type": "Answer", "text": f["summary"]}} for f in faqs]
    return mark_safe(json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))  # noqa: S308
