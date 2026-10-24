"""قالب پروژه‌ها: فهرست کدهای عارضه‌ای که هنگام ساخت پروژه در جدول codes ریخته می‌شود."""

# (کد، نام، نوع هندسه، لایه)
TEMPLATES = {
    "blank": ("خالی", []),
    "topo": ("توپوگرافی", [
        ("GR", "زمین طبیعی", "point", "terrain"),
        ("RD", "محور راه", "line", "road"),
        ("BL", "ساختمان", "polygon", "building"),
        ("PL", "تیر برق", "point", "utility"),
        ("TR", "درخت", "point", "vegetation"),
        ("FN", "حصار", "line", "boundary"),
    ]),
    "cadastre": ("کاداستر و مرز ملک", [
        ("BP", "نشانه مرزی", "point", "boundary"),
        ("PR", "قطعه", "polygon", "parcel"),
        ("BN", "حد ملک", "line", "boundary"),
        ("CP", "نقطه کنترل", "point", "control"),
    ]),
}


def template_choices():
    return [(k, v[0]) for k, v in TEMPLATES.items()]
