"""سیستم مختصات پروژه‌های برداشت: منطقه UTM ایران و اعتبارسنجی SRID."""
import math

UTM_IRAN = {38: 32638, 39: 32639, 40: 32640, 41: 32641}  # شمالی؛ ایران بین ۳۸ تا ۴۱
WGS84 = 4326
PRESETS = [
    (32639, "UTM منطقه ۳۹ شمالی (تهران، مرکز و شمال)"),
    (32640, "UTM منطقه ۴۰ شمالی (شرق)"),
    (32638, "UTM منطقه ۳۸ شمالی (غرب)"),
    (32641, "UTM منطقه ۴۱ شمالی (شرق دور)"),
    (WGS84, "WGS84 جغرافیایی (طول و عرض)"),
]


def preset_tiles() -> list[tuple[int, str, str]]:
    """(srid، عنوان کوتاه، توضیح) برای کاشی‌های انتخاب سیستم مختصات."""
    out = []
    for srid, label in PRESETS:
        title, _, hint = label.partition(" (")
        out.append((srid, title, hint.rstrip(")")))
    return out


class CrsError(ValueError):
    pass


def utm_zone(lon: float) -> int:
    if not -180 <= lon <= 180:
        raise CrsError("طول جغرافیایی باید بین ۱۸۰- و ۱۸۰ باشد.")
    return min(int(math.floor((lon + 180) / 6)) + 1, 60)


def utm_srid(lon: float, lat: float = 1.0) -> int:
    """SRID منطقه UTM برای نقطه‌ای با طول جغرافیایی داده‌شده (شمالی یا جنوبی بر اساس عرض)."""
    return (32600 if lat >= 0 else 32700) + utm_zone(lon)


def is_preset(srid: int) -> bool:
    return srid == WGS84 or srid in UTM_IRAN.values()


def validate_srid(srid, conn=None) -> int:
    """SRID پیش‌ساخته همیشه مجاز است؛ دیگری فقط اگر در spatial_ref_sys پایگاه داده کاربر باشد."""
    try:
        srid = int(srid)
    except (TypeError, ValueError):
        raise CrsError("سیستم مختصات نامعتبر است.") from None
    if is_preset(srid):
        return srid
    if conn is None or srid <= 0:
        raise CrsError("سیستم مختصات پشتیبانی نمی‌شود.")
    if conn.execute("SELECT 1 FROM spatial_ref_sys WHERE srid = %s", (srid,)).fetchone() is None:
        raise CrsError("این سیستم مختصات در پایگاه داده شما نیست.")
    return srid
