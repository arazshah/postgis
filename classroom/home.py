"""سهم پلاگین کلاس درس در صفحه‌ی خانه: آیا کاربر مدرس است؟"""
from .services import teacher_contracts


def context(request, dbs):
    user = request.user
    return {"is_teacher": teacher_contracts(user).exists() or user.taught_classes.exists()}
