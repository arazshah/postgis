"""واکنش پلاگین انتشار به رویدادهای فضای کار؛ در plugin.py ثبت می‌شود."""
import logging

log = logging.getLogger(__name__)


def workspace_deleted(*, ws, **_):
    """فایل‌های پروژه QGIS Server این پایگاه داده (شامل رمز نقش فقط‌خواندنی) پاک شوند."""
    from .models import Service
    from .ows import remove_service_files

    service = Service.objects.filter(database=ws).first()
    if service:
        try:
            remove_service_files(service)
        except OSError:
            log.exception("remove ows files for %s", ws.pk)
        service.ows_password_encrypted = ""
        service.save(update_fields=["ows_password_encrypted"])
