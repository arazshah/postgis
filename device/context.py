from django.conf import settings


def device(request):
    return {
        "DEVICE_MODE": True,
        "DEVICE_NAME": settings.DEVICE_NAME,
        "DEVICE_VERSION": settings.DEVICE_VERSION,
        "ROBOTS": "noindex, nofollow",
    }
