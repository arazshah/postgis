"""سهم پلاگین صورتحساب در صفحه‌ی خانه: ووچرهای استفاده‌نشده."""
from .services import unused_vouchers


def context(request, dbs):
    return {"vouchers": unused_vouchers(request.user)}
