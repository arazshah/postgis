"""ارائه‌دهنده‌ی فروش پلاگین برای kernel.market: آگهی ← `PluginAddon` (همان فروشگاه و فاکتور افزونه‌ی موجود)."""
from kernel.market import Listing

from .models import PluginAddon


def handle(action: str, plugin_id: str, listing: Listing | None) -> None:
    addon = PluginAddon.objects.filter(plugin_id=plugin_id).order_by("pk").first()
    if action == "remove":
        if addon is not None:
            addon.is_public = False
            addon.save(update_fields=["is_public"])
        return
    scope = PluginAddon.Scope.USER if listing.scope == "user" else PluginAddon.Scope.WORKSPACE
    fields = {"title": listing.title[:80], "description": listing.summary[:240], "price_toman": int(listing.price_toman),
              "duration_days": int(listing.duration_days), "scope": scope, "trial_days": int(listing.trial_days),
              "limits": dict(listing.limits), "is_public": bool(listing.is_public)}
    if addon is None:
        PluginAddon.objects.create(plugin_id=plugin_id, **fields)
    else:
        for k, v in fields.items():
            setattr(addon, k, v)
        addon.save()
