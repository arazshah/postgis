"""زمان ارسال بهینه: هر کاربر نزدیک ساعتی که معمولاً خودش وارد می‌شود؛ هرگز شب/صبح زود/جمعه.

- ساعت‌های ورود ۹۰ روز اخیر کاربر (رویداد LOGIN) را می‌شماریم؛ ساعت پرتکرار، اگر دست‌کم ۳ ورود باشد.
- بدون سابقه: ۱۱ صبح (پنجره‌ی «تمرکز کاری»)، با پراکندگی دقیقه برای جلوگیری از ازدحام.
- پنجره‌ی مجاز: ۱۰ تا ۱۹:۵۹ (پنجشنبه تا ۱۳)، جمعه هرگز.
"""
from __future__ import annotations

import datetime
from collections import Counter
from zoneinfo import ZoneInfo

from django.utils import timezone

TZ = ZoneInfo("Asia/Tehran")
OPEN_HOUR, CLOSE_HOUR, THURSDAY_CLOSE, DEFAULT_HOUR, MIN_LOGINS, FRIDAY = 10, 20, 14, 11, 3, 4


def preferred_hour(user) -> tuple[int, bool]:
    """(ساعت، آیا از رفتار خود کاربر یاد گرفته شد)."""
    from analytics.models import Event

    since = timezone.now() - datetime.timedelta(days=90)
    stamps = list(Event.objects.filter(visitor__user=user, name=Event.LOGIN, created_at__gte=since)
                  .values_list("created_at", flat=True)[:200])
    if len(stamps) >= MIN_LOGINS:
        hour = Counter(s.astimezone(TZ).hour for s in stamps).most_common(1)[0][0]
        return min(max(hour, OPEN_HOUR), CLOSE_HOUR - 1), True
    return DEFAULT_HOUR, False


def in_window(moment: datetime.datetime) -> bool:
    local = moment.astimezone(TZ)
    if local.weekday() == FRIDAY:
        return False
    close = THURSDAY_CLOSE if local.weekday() == 3 else CLOSE_HOUR
    return OPEN_HOUR <= local.hour < close


def best_time(user, after: datetime.datetime, salt: int = 0) -> datetime.datetime:
    """نخستین لحظه‌ی مناسب بعد از `after` (حداقل ۳۰ دقیقه بعد)."""
    hour, _ = preferred_hour(user)
    minute = (user.pk * 7 + salt) % 30  # پراکندگی ثابت برای هر کاربر
    earliest = after.astimezone(TZ) + datetime.timedelta(minutes=30)
    day = earliest.date()
    for _ in range(10):
        h = hour
        if day.weekday() == 3:
            h = min(h, THURSDAY_CLOSE - 1)
        cand = datetime.datetime(day.year, day.month, day.day, h, minute, tzinfo=TZ)
        if day.weekday() != FRIDAY and cand >= earliest:
            return cand
        day += datetime.timedelta(days=1)
    return earliest
