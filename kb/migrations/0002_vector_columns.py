from django.db import migrations

from kb import vectors


def add_vector_columns(apps, schema_editor):
    # اگر افزونه vector در دسترس نباشد بی‌صدا رد می‌شود؛ دستیار با جست‌وجوی کلیدواژه‌ای کار می‌کند
    # و بعد از تعویض ایمیج، دستور kb_embed ستون‌ها را می‌سازد.
    vectors.setup(schema_editor.connection)


class Migration(migrations.Migration):

    dependencies = [
        ("kb", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(add_vector_columns, migrations.RunPython.noop),
    ]
