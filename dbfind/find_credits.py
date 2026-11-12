"""اعتبار «یافتن عارضه»: فقط جست‌وجوهایی که شرط مکانی‌شان لایه‌ی دیگری است از اعتبار پلن کم می‌کنند.

- دوره: ۳۰ روز گذشته، برای هر پایگاه داده (همه‌ی اعضای تیم از یک اعتبار).
- همان پرسش (همان مشخصه) در ۳۰ دقیقه‌ی بعد دوباره کم نمی‌شود؛ ورق زدن نتیجه و اجرای دوباره رایگان است.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from databases.models import FindLog, UserDatabase

PERIOD = timedelta(days=30)
REPEAT_FREE = timedelta(minutes=30)


def status(db: UserDatabase) -> dict:
    cap = db.plan.find_layer_credits if db.plan_id else 0
    used = FindLog.objects.filter(database=db, charged=True, created_at__gte=timezone.now() - PERIOD).count()
    return {"cap": cap, "used": used, "left": max(cap - used, 0)}


def _recent_same(db: UserDatabase, spec_hash: str) -> bool:
    return FindLog.objects.filter(database=db, spec_hash=spec_hash, charged=True,
                                  created_at__gte=timezone.now() - REPEAT_FREE).exists()


def check(db: UserDatabase, spec_hash: str, cross_layer: bool) -> bool:
    """آیا اجرای این پرسش مجاز است؟ (بدون ثبت)"""
    if not cross_layer or _recent_same(db, spec_hash):
        return True
    return status(db)["left"] > 0


def record(db: UserDatabase, user, spec_hash: str, layer: str, cross_layer: bool) -> bool:
    """ثبت یک جست‌وجوی موفق؛ خروجی: آیا از اعتبار کم شد."""
    with transaction.atomic():
        UserDatabase.objects.select_for_update().filter(pk=db.pk).first()  # جلوی مصرف هم‌زمان بیش از اعتبار
        charge = cross_layer and not _recent_same(db, spec_hash)
        FindLog.objects.create(database=db, user=user if getattr(user, "pk", None) else None, spec_hash=spec_hash,
                               layer=layer[:130], cross_layer=cross_layer, charged=charge)
    return charge
