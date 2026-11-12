from django.core.management.base import BaseCommand

from kernel import extpreflight


class Command(BaseCommand):
    help = ("پیش‌پرواز شروع پلاگین‌های سطح ۳: هر پلاگین در زیرپردازه‌ی جدا (و با --migrate مهاجرتش) سنجیده می‌شود؛ "
            "ناموفق‌ها برای همین بوت کنار می‌روند. خروجی --shell برای entrypoint.")

    def add_arguments(self, parser):
        parser.add_argument("--migrate", action="store_true", help="مهاجرت هر پلاگین را هم (جدا) اجرا کن")
        parser.add_argument("--shell", action="store_true", help="فقط خروجی قابل eval برای entrypoint")

    def handle(self, migrate=False, shell=False, **options):
        res = extpreflight.run(migrate=migrate)
        extpreflight.write_marker(res)
        if shell:
            self.stdout.write(extpreflight.shell_env(res))
            return
        if not res.ids:
            self.stdout.write("پلاگینی در ext/ نیست.")
        for pid in res.ids:
            self.stdout.write(f"{pid}: {'کنار گذاشته شد — ' + res.disabled[pid] if pid in res.disabled else 'سالم'}")
        if res.safe_mode:
            self.stdout.write(f"حالت امن: {res.reason}")
