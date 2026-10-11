"""داده‌های پیش‌فرض: فهرست افزونه‌ها و پلن رایگان."""

EXTENSIONS = [
    # name, title, description, is_default, is_heavy, order
    ("postgis", "PostGIS (هسته مکانی)",
     "انواع داده geometry و geography، توابع مکانی و نمایه مکانی. برای هر کار مکانی لازم است.", True, False, 1),
    ("postgis_topology", "توپولوژی",
     "مدیریت توپولوژی لایه‌ها (همسایگی، مرز مشترک) مثل نقشه‌های کاداستر.", False, False, 2),
    ("postgis_raster", "رستر",
     "ذخیره و تحلیل داده‌های رستری (تصاویر ماهواره‌ای، DEM). حجم را سریع پر می‌کند.", False, True, 3),
    ("pgrouting", "مسیریابی (pgRouting)",
     "کوتاه‌ترین مسیر، تحلیل شبکه و حوزه دسترسی روی شبکه معابر.", False, False, 4),
    ("postgis_sfcgal", "هندسه سه‌بعدی (SFCGAL)", "عملیات پیشرفته سه‌بعدی و هندسه دقیق.", False, False, 5),
    ("fuzzystrmatch", "تطبیق تقریبی متن", "جستجوی شبیه کلمات؛ مفید برای نشانی‌ها و نام مکان‌ها.", False, False, 6),
    ("pg_trgm", "جستجوی متنی سریع (trigram)", "جستجوی LIKE سریع و تشابه متنی روی نام عوارض.", False, False, 7),
    ("hstore", "کلید-مقدار (hstore)", "ذخیره ویژگی‌های متغیر؛ رایج در داده‌های OpenStreetMap.", False, False, 8),
    ("uuid-ossp", "شناسه یکتا (UUID)", "تولید شناسه یکتای جهانی برای عوارض.", False, False, 9),
]

FREE_PLAN = {
    "slug": "free",
    "name": "رایگان",
    "description": "مناسب یادگیری، پایان‌نامه و پروژه‌های کوچک WebGIS.",
    "quota_mb": 1024,
    "max_connections": 5,
    "duration_days": 90,
    "statement_timeout_s": 60,
    "temp_file_limit_mb": 1024,
    "backup_retention_days": 3,
    "price_toman": 0,
    "is_free": True,
    "is_public": True,
    "is_default": True,
    "is_renewable": True,
    "order": 1,
}


def seed():
    from .models import Extension, Plan

    for name, title, desc, is_default, heavy, order in EXTENSIONS:
        Extension.objects.update_or_create(
            name=name,
            defaults={"title": title, "description": desc, "is_default": is_default, "is_heavy": heavy,
                      "order": order},
        )
    if not Plan.objects.filter(slug=FREE_PLAN["slug"]).exists():
        Plan.objects.create(**FREE_PLAN)
