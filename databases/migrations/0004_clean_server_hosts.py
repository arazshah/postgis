"""اگر قبلاً آدرس کامل postgres://... در فیلد host ذخیره شده، آن را تجزیه و رمز را رمزنگاری می‌کند."""
from django.db import migrations


def forwards(apps, schema_editor):
    from databases.crypto import encrypt
    from databases.models import parse_postgres_url

    DatabaseServer = apps.get_model("databases", "DatabaseServer")
    for server in DatabaseServer.objects.all():
        changed = False
        for field in ("host", "public_host"):
            parsed = parse_postgres_url(getattr(server, field))
            if not parsed:
                continue
            setattr(server, field, parsed["host"])
            changed = True
            if field == "host":
                if parsed["port"]:
                    server.port = parsed["port"]
                if parsed["user"]:
                    server.admin_user = parsed["user"]
                if parsed["dbname"]:
                    server.admin_database = parsed["dbname"]
                if parsed["password"]:
                    server.admin_password_encrypted = encrypt(parsed["password"])
        if changed:
            server.save()


class Migration(migrations.Migration):
    dependencies = [("databases", "0003_help_text_domain")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
