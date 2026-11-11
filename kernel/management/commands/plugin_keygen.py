import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "کلید ناشر پلاگین (Ed25519) می‌سازد: فایل کلید خصوصی (فقط CI) و خط کلید عمومی برای PLUGIN_PUBLISHER_KEYS."

    def add_arguments(self, parser):
        parser.add_argument("publisher", help="نام ناشر، مثلاً geopaygah")
        parser.add_argument("--out", required=True, help="مسیر فایل کلید خصوصی (ساخته می‌شود؛ بازنویسی نمی‌شود)")

    def handle(self, publisher, out, **options):
        path = Path(out)
        if path.exists():
            raise CommandError(f"{path} وجود دارد؛ کلید قبلی را بازنویسی نمی‌کنم.")
        key = Ed25519PrivateKey.generate()
        raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(base64.b64encode(raw).decode() + "\n")
        pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.stdout.write(f"کلید خصوصی در {path} نوشته شد (آن را فقط در CI نگه دارید و هرگز commit نکنید).")
        self.stdout.write("برای تنظیم استقرار (PLUGIN_PUBLISHER_KEYS):")
        self.stdout.write(f"{publisher}={base64.b64encode(pub).decode()}")
