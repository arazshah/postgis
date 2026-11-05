"""مقدار اولیه‌ی صفحه‌ی اعتماد و اولین عضو تیم؛ بعد از این‌ها همه چیز از پنل مدیریت ویرایش می‌شود."""
from pathlib import Path

from django.db import migrations

ITEMS = [
    ("server", "سرورها در ایران، دیتاسنتر پارس‌پک", "always",
     "پنل و پایگاه‌های داده‌ی مشتریان روی سرورهای شرکت پارس‌پک در ایران اجرا می‌شوند و داده‌ی شما و بکاپ‌هایش همان‌جا "
     "نگهداری می‌شود.", "", ""),
    ("db", "نسخه‌ی دوم بکاپ در فضای ابری جداگانه", "offsite",
     "از هر بکاپ یک نسخه‌ی رمزنگاری‌شده در فضای ابری جداگانه‌ای در پارس‌پک، بیرون از سرور اصلی، هم نگه داشته می‌شود "
     "تا خرابی یک سرور داده‌تان را از بین نبرد.", "", ""),
    ("db", "بکاپ شبانه", "always",
     "هر شب بعد از ساعت ۳ بامداد از پایگاه داده‌تان بکاپ کامل گرفته می‌شود و طبق پلن نگه داشته می‌شود. "
     "بکاپ‌ها به‌صورت دوره‌ای آزمون بازگردانی می‌شوند تا مطمئن باشیم سالم‌اند.", "", ""),
    ("lock", "اتصال رمزنگاری‌شده", "always",
     "اتصال بدون SSL پذیرفته نمی‌شود. هر پایگاه داده نام، نقش و رمز جدا دارد و کاربران دیگر به آن دسترسی ندارند.", "", ""),
    ("lock", "دیسک سرورها رمزنگاری‌شده است", "disk",
     "داده‌ی ذخیره‌شده روی دیسک سرورها رمزنگاری شده است.", "", ""),
    ("users", "چه کسی به داده‌ی شما دسترسی دارد؟", "always",
     "دسترسی مدیریتی به سرورها فقط در اختیار مدیر فنی است، با تدابیر امنیتی محافظت می‌شود و تنها در موارد اضطراری و "
     "برای رفع مشکل فنی استفاده می‌شود. لایه‌های شما تا وقتی خودتان منتشر نکنید خصوصی می‌مانند.", "", ""),
    ("download", "داده‌ی شما مال شماست؛ هر وقت خواستید ببرید", "always",
     "هر زمان می‌توانید بکاپ کامل را در قالب استاندارد PostgreSQL دانلود کنید و روی هر سرور دیگری بازگردانید. "
     "از هر جدول هم خروجی GeoPackage، GeoJSON، CSV و … می‌گیرید. قفل فروشنده ندارید.", "", ""),
    ("trash", "بعد از حذف یا پایان اعتبار چه می‌شود؟", "always",
     "پایگاه داده‌ی منقضی‌شده مهلت تمدید دارد و بعد از آن حذف می‌شود. بکاپ‌ها بعد از پایان مدت نگهداری پلن پاک "
     "می‌شوند و بعد از حذف پایگاه داده در دسترس نیستند؛ پس بکاپ مهم را روی کامپیوتر خودتان هم نگه دارید.", "", ""),
    ("spark", "دستیار هوش مصنوعی اختیاری است", "always",
     "فقط وقتی «پرسش فارسی» یا دستیار را خودتان به کار ببرید، متن پرسش (و ساختار جدول‌ها) برای ساخت پاسخ به سرویس مدل "
     "زبانی انتخابی شما فرستاده می‌شود. برای داده‌ی حساس از آن استفاده نکنید.", "", ""),
    ("cube", "نصب اختصاصی روی سرور سازمان شما", "always",
     "اگر سیاست سازمان شما اجازه نمی‌دهد داده از شبکه‌ی داخلی بیرون برود، همین سامانه را می‌توانیم روی سرور خودتان نصب "
     "و راه‌اندازی کنیم.", "درخواست نصب اختصاصی", "/contact/?topic=onprem"),
]


def seed(apps, schema_editor):
    TrustItem = apps.get_model("core", "TrustItem")
    TeamMember = apps.get_model("core", "TeamMember")
    SiteSettings = apps.get_model("core", "SiteSettings")
    if not TrustItem.objects.exists():
        for i, (icon, title, when, body, label, url) in enumerate(ITEMS, 1):
            TrustItem.objects.create(icon=icon, title=title, show_when=when, body=body, link_label=label,
                                     link_url=url, order=i * 10)
    conf = SiteSettings.objects.filter(pk=1).first()
    if conf is not None and not conf.support_phone:
        conf.support_phone = "09397526657"
        conf.save(update_fields=["support_phone"])
    if not TeamMember.objects.exists():
        photo = Path(__file__).resolve().parent.parent / "seed" / "araz-shah-karami.jpg"
        TeamMember.objects.create(
            name="آراز شاه کرمی", role="بنیان‌گذار و مدیر فنی",
            bio="این سرویس را ساخته‌ام تا کار با پایگاه داده مکانی برای کاربران GIS ایران ساده شود. "
                "برای هر پرسش یا جلسه‌ی معرفی، مستقیم با خودم در تماس باشید.",
            photo_data=photo.read_bytes() if photo.exists() else None,
            photo_mime="image/jpeg" if photo.exists() else "", photo_version=1,
            linkedin=(conf.social_linkedin if conf else ""), instagram=(conf.social_instagram if conf else ""),
            order=10)


class Migration(migrations.Migration):
    dependencies = [("core", "0016_trust_team_contact")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
