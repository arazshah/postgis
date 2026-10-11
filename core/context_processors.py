from django.conf import settings

from .models import SiteSettings


def site(request):
    conf = SiteSettings.get()
    return {
        "SITE": conf,
        "SITE_NAME": conf.site_name,
        "SITE_URL": settings.SITE_URL,
        "SUPPORT_TELEGRAM": conf.support_telegram,
        "SUPPORT_EMAIL": conf.support_email,
    }
