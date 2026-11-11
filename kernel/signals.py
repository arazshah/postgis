"""تغییر هر مدل مجوز، حافظه‌ی موتور مجوز همین پردازه را فوراً باطل می‌کند (پردازه‌های دیگر ظرف TTL)."""
from django.db.models.signals import post_delete, post_save

from . import entitlements


def _drop(**_):
    entitlements.invalidate()


def connect():
    from .models import Entitlement, OrgMember, PluginRelease, PluginState

    for model in (PluginState, Entitlement, OrgMember, PluginRelease):
        post_save.connect(_drop, sender=model, dispatch_uid=f"kernel.inv.save.{model.__name__}")
        post_delete.connect(_drop, sender=model, dispatch_uid=f"kernel.inv.del.{model.__name__}")
