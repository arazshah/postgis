import signal
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from jobs import services

HEARTBEAT = Path("/tmp/worker.alive")


class Command(BaseCommand):
    help = "سرویس پس‌زمینه: بکاپ شبانه، بکاپ و بازگردانی درخواستی، آزمون بازگردانی، پاک‌سازی و هشدار."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="فقط کارهای فعلی صف را اجرا کن و خارج شو")

    def handle(self, *args, once=False, **options):
        self.stop = False
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stop", True))
        last_tick = 0.0
        self.stdout.write("worker started")
        while not self.stop:
            close_old_connections()
            HEARTBEAT.touch()
            if time.monotonic() - last_tick > 60 or once:
                try:
                    self.stdout.write(f"tick {services.tick()}")
                except Exception as exc:  # noqa: BLE001
                    self.stderr.write(f"tick failed: {exc}")
                last_tick = time.monotonic()
            job = services.claim_next()
            if job is not None:
                self.stdout.write(f"run {job}")
                services.run(job)
                self.stdout.write(f"  -> {job.status} {job.message[:160]}")
                continue
            if once:
                break
            time.sleep(3)
