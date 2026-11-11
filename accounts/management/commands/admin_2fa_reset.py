from django.core.management.base import BaseCommand, CommandError

from accounts.models import AdminTOTP, User


class Command(BaseCommand):
    help = "ورود دومرحله‌ی یک مدیر را بازنشانی می‌کند (دستگاه گم‌شده و کدهای بازیابی تمام‌شده)؛ ورود بعدی ثبت‌نام تازه می‌خواهد."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, username, **options):
        user = User.objects.filter(username=username, is_staff=True).first()
        if user is None:
            raise CommandError("مدیری با این نام کاربری نیست.")
        n, _ = AdminTOTP.objects.filter(user=user).delete()
        self.stdout.write(f"ورود دومرحله‌ی {username} بازنشانی شد." if n else f"{username} ثبت‌نام دومرحله‌ای نداشت.")
