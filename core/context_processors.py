from django.conf import settings

from .models import SiteSettings

PRIVATE_PREFIXES = ("/dashboard/", "/accounts/", "/billing/", "/support/", "/manage/")


def site(request):
    conf = SiteSettings.get()
    return {
        "CANONICAL_URL": settings.CANONICAL_URL + request.path,
        "BASE_URL": settings.CANONICAL_URL,
        "ROBOTS": "noindex, nofollow" if request.path.startswith(PRIVATE_PREFIXES) else "index, follow",
        "SITE": conf,
        "SITE_NAME": conf.site_name,
        "SITE_URL": settings.SITE_URL,
        "SUPPORT_TELEGRAM": conf.support_telegram,
        "SUPPORT_EMAIL": conf.support_email,
    }
