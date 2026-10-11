from django.db import migrations


def forwards(apps, schema_editor):
    from databases.defaults import EXTENSIONS, FREE_PLAN

    Extension = apps.get_model("databases", "Extension")
    Plan = apps.get_model("databases", "Plan")
    for name, title, desc, is_default, heavy, order in EXTENSIONS:
        Extension.objects.update_or_create(
            name=name, defaults={"title": title, "description": desc, "is_default": is_default,
                                 "is_heavy": heavy, "order": order})
    if not Plan.objects.filter(slug=FREE_PLAN["slug"]).exists():
        Plan.objects.create(**FREE_PLAN)


class Migration(migrations.Migration):
    dependencies = [("databases", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
