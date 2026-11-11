"""نمودارهای ساده‌ی SVG برای صفحه‌های مصرف (بدون کتابخانه)؛ سهم پلاگین‌ها هم از همین استفاده می‌کنند."""
from datetime import datetime, time

from django.utils import timezone


def bars(values, days, cap=None, width=600, height=140):
    """نمودار ستونی ساده SVG (بدون کتابخانه): مقادیر و خط سقف."""
    if not values:
        return None
    top = max(max(values), 1)
    if cap and cap < top * 3:
        top = max(top, cap)
    n = len(values)
    gap = 4
    bw = max(2, (width - gap * (n - 1)) / n)
    bars = []
    for i, (v, d) in enumerate(zip(values, days, strict=True)):
        d = timezone.make_aware(datetime.combine(d, time(12)))  # فیلتر jdate تاریخ‌وزمان می‌خواهد
        h = 0 if not v else max(2, round(v / top * (height - 6)))
        bars.append({"x": round(i * (bw + gap), 1), "y": height - h, "w": round(bw, 1), "h": h, "v": v, "day": d})
    cap_y = round(height - cap / top * (height - 6), 1) if cap and cap <= top else None
    return {"bars": bars, "w": width, "h": height, "cap_y": cap_y}
