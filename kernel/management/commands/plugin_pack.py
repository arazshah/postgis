import base64
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core.management.base import BaseCommand, CommandError

from kernel import pkg


class Command(BaseCommand):
    help = "پوشه‌ی پلاگین (plugin.toml و pages/*.toml) را می‌بندد و با کلید ناشر امضا می‌کند؛ بررسی ایستا را هم نشان می‌دهد."

    def add_arguments(self, parser):
        parser.add_argument("directory")
        parser.add_argument("--key", required=True, help="فایل کلید خصوصی (خروجی plugin_keygen)")
        parser.add_argument("--publisher", required=True)
        parser.add_argument("--out", required=True, help="مسیر فایل خروجی، مثلاً fleet-1.0.0.gpkgx")
        parser.add_argument("--tests", action="store_true", help="آزمون‌های بسته‌ی سطح ۲ را هم اجرا کن (PLUGIN_RUNNER_MODE=local در CI نویسنده)")

    def handle(self, directory, key, publisher, out, tests=False, **options):
        root = Path(directory)
        files = {}
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = path.relative_to(root).as_posix()
            if rel == pkg.SIG_NAME:
                continue
            if not pkg.NAME_RE.match(rel):
                raise CommandError(f"فایل «{rel}» در بسته مجاز نیست (مجاز: plugin.toml، pages/*.toml، README.md).")
            files[rel] = path.read_bytes()
        try:
            priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(Path(key).read_text().strip()))
        except Exception as exc:  # noqa: BLE001
            raise CommandError("فایل کلید خصوصی خوانده نشد.") from exc
        files[pkg.SIG_NAME] = pkg.sign(files, priv, publisher)
        data = pkg.pack(files)
        Path(out).write_bytes(data)
        self.stdout.write(f"{out}: {len(data):,} بایت، {len(files)} فایل")
        pub = priv.public_key()
        ins = pkg.inspect(data, keys={publisher: pub}, run_tests=tests)
        for s in ins.steps:
            self.stdout.write(f"  {'✓' if s.ok else '✗'} {s.stage}{': ' + s.detail if s.detail else ''}")
        if not ins.ok:
            raise CommandError("بررسی ایستا موفق نبود؛ بسته ساخته شد ولی بارگذاری نکنید.")
