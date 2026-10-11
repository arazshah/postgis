from django.conf import settings


def site(request):
    return {
        "SITE_NAME": settings.SITE_NAME,
        "SITE_URL": settings.SITE_URL,
        "SUPPORT_TELEGRAM": settings.SUPPORT_TELEGRAM,
        "SUPPORT_EMAIL": settings.SUPPORT_EMAIL,
    }
