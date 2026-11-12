"""مرحله‌ی ۲ سطح ۳: ext_check روی نمونه‌های خوب و بد (هر قاعده‌ی ۴.۳ تا ۴.۵ یک نمونه‌ی ردشونده)."""
import tempfile
import textwrap
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from kernel import extcheck

APPS = '''
from django.apps import AppConfig
class C(AppConfig):
    name = "ext.demo"
    label = "x_demo"
'''
PLUGIN = '''
from kernel import routes
from kernel.plugins import register
register("demo", "نمونه", kind="custom", tier=3)
routes.add("ws_ext", "demo/home/", "ext.demo.views.home", "home", plugin="demo")
'''
MODELS = '''
from django.db import models
class Thing(models.Model):
    db = models.ForeignKey("databases.UserDatabase", on_delete=models.CASCADE)
    owner = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL)
    parent = models.ForeignKey("self", null=True, on_delete=models.SET_NULL)
'''
MIG = '''
from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies = [("x_demo", "0001_initial"), ("databases", "0001_initial")]
    operations = [
        migrations.CreateModel(name="Thing", fields=[("id", models.AutoField(primary_key=True))]),
        migrations.AddField(model_name="thing", name="note", field=models.TextField(null=True)),
    ]
'''


def make(**files) -> Path:
    """ext/demo با فایل‌های خوب و جایگزین/افزوده‌ی files (نام فایل با __ برای پوشه)."""
    root = Path(tempfile.mkdtemp()) / "demo"
    (root / "tests").mkdir(parents=True)
    (root / "migrations").mkdir()
    base = {"apps.py": APPS, "plugin.py": PLUGIN, "models.py": MODELS, "views.py": "def home(request):\n    return None\n",
            "tests/test_a.py": "x = 1\n", "migrations/__init__.py": "", "migrations/0001_initial.py": MIG}
    base.update({k.replace("__", "/") + ".py": v for k, v in files.items() if v is not None})
    for k in [k for k, v in files.items() if v is None]:
        base.pop(k.replace("__", "/") + ".py", None)
    for rel, text in base.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(textwrap.dedent(text))
    return root


def errors(root: Path) -> list[str]:
    return [str(f) for f in extcheck.check_plugin(root) if f.level == "error"]


class GoodPluginTests(SimpleTestCase):
    def test_clean_plugin_passes(self):
        self.assertEqual(errors(make()), [])


class StructureTests(SimpleTestCase):
    def test_wrong_label(self):
        self.assertTrue(any("x_demo" in e for e in errors(make(apps=APPS.replace("x_demo", "demo")))))

    def test_wrong_name(self):
        self.assertTrue(any("ext.demo" in e for e in errors(make(apps=APPS.replace("ext.demo", "demo")))))

    def test_missing_files(self):
        self.assertTrue(any("apps.py" in e for e in errors(make(apps=None))))
        self.assertTrue(any("plugin.py" in e for e in errors(make(plugin=None))))

    def test_tier_must_be_3(self):
        self.assertTrue(any("tier=3" in e for e in errors(make(plugin=PLUGIN.replace("tier=3", "tier=1")))))

    def test_register_id_must_match_folder(self):
        self.assertTrue(any("register" in e for e in errors(make(plugin=PLUGIN.replace('"demo", "نمونه"', '"other", "x"')))))

    def test_global_urls_forbidden(self):
        self.assertTrue(any("urls.py" in e for e in errors(make(urls="urlpatterns = []\n"))))

    def test_bad_route_group_and_prefix(self):
        bad = PLUGIN.replace('"ws_ext"', '"databases"')
        self.assertTrue(any("databases" in e for e in errors(make(plugin=bad))))
        bad = PLUGIN.replace('"demo/home/"', '"home/"')
        self.assertTrue(any("demo/" in e for e in errors(make(plugin=bad))))

    def test_bad_folder_name(self):
        root = make()
        other = root.parent / "Bad-Name"
        root.rename(other)
        self.assertTrue(errors(other))

    def test_test_required(self):
        root = make()
        (root / "tests" / "test_a.py").unlink()
        (root / "tests").rmdir()
        self.assertTrue(any("آزمون" in e for e in errors(root)))

    def test_syntax_error_reported(self):
        self.assertTrue(any("تجزیه" in e for e in errors(make(views="def (:\n"))))


class CodeScanTests(SimpleTestCase):
    def bad(self, code, needle):
        errs = errors(make(extra=code))
        self.assertTrue(any(needle in e for e in errs), errs)

    def test_signal_on_foreign_model(self):
        self.bad("from django.db.models.signals import post_save\n@receiver(post_save, sender=User)\ndef f(**k): pass\n", "سیگنال")
        self.bad("from django.db.models.signals import post_save\npost_save.connect(f, sender=User)\n", "سیگنال")

    def test_signal_on_own_model_ok(self):
        code = "from django.db.models.signals import post_save\nclass M: pass\npost_save.connect(f, sender=M)\n"
        self.assertEqual([e for e in errors(make(extra=code)) if "سیگنال" in e], [])

    def test_meta_rules(self):
        self.bad("class M:\n    class Meta:\n        db_table = 'x'\n", "db_table")
        self.bad("class M:\n    class Meta:\n        managed = False\n", "managed")
        self.bad("class M:\n    class Meta:\n        proxy = True\n", "proxy")

    def test_settings_mutation(self):
        self.bad("from django.conf import settings\nsettings.MIDDLEWARE = []\n", "MIDDLEWARE")
        self.bad("from django.conf import settings\nsettings.MIDDLEWARE.append('x')\n", "MIDDLEWARE")

    def test_secrets(self):
        self.bad("from django.conf import settings\nk = settings.SECRET_KEY\n", "SECRET_KEY")
        self.bad("from django.conf import settings\nk = settings.CREDENTIALS_ENCRYPTION_KEY\n", "CREDENTIALS")

    def test_raw_cursor(self):
        self.bad("from django.db import connection\nconnection.cursor()\n", "cursor")

    def test_monkeypatch(self):
        self.bad("import json\njson.loads = None\n", "monkeypatch")
        self.bad("import json\nsetattr(json, 'x', 1)\n", "monkeypatch")

    def test_warn_list_needs_allow(self):
        self.bad("import subprocess\n", "subprocess")
        self.bad("import pickle\n", "pickle")
        self.bad("import ctypes\n", "ctypes")
        self.bad("import socket\n", "socket")
        self.bad("eval('1')\n", "eval")
        self.bad("import os\nos.system('x')\n", "system")

    def test_allow_comment_downgrades_to_warning(self):
        root = make(extra="import subprocess  # ext: allow(برای فراخوانی ابزار خارجی)\n")
        self.assertEqual(errors(root), [])
        warns = [f for f in extcheck.check_plugin(root) if f.level == "warn"]
        self.assertTrue(warns and "ابزار خارجی" in warns[0].message)

    def test_allow_needs_reason(self):
        self.bad("import subprocess  # ext: allow()\n", "subprocess")

    def test_allow_does_not_unlock_hard_bans(self):
        self.bad("from django.conf import settings\nk = settings.SECRET_KEY  # ext: allow(لازم دارم)\n", "SECRET_KEY")

    def test_tests_dir_is_not_scanned(self):
        self.assertEqual(errors(make(tests__test_a="import subprocess\nfrom django.conf import settings\nsettings.SECRET_KEY\n")), [])

    def test_fk_rules(self):
        self.bad("from django.db import models\nclass A:\n    x = models.ForeignKey('databases.UserDatabase', on_delete=models.PROTECT)\n", "on_delete")
        self.bad("from django.db import models\nclass A:\n    x = models.ForeignKey('billing.Invoice', on_delete=models.CASCADE)\n", "billing.Invoice")
        self.bad("from django.db import models\nclass A:\n    x = models.ForeignKey('databases.UserDatabase')\n", "on_delete")


class MigrationTests(SimpleTestCase):
    def mig(self, ops, deps='("x_demo", "0001_initial")'):
        return make(migrations__0002_next=(
            "from django.db import migrations, models\nclass Migration(migrations.Migration):\n"
            f"    dependencies = [{deps}]\n    operations = [{ops}]\n"))

    def test_safe_ops_ok(self):
        self.assertEqual(errors(self.mig("migrations.AddIndex(model_name='thing', index=models.Index(fields=['id'], name='i'))")), [])

    def test_privileged_ops_need_marker(self):
        for op in ("migrations.RunPython(f)", "migrations.RunSQL('x')", "migrations.DeleteModel('Thing')",
                   "migrations.RemoveField('thing', 'id')", "migrations.RenameField('thing', 'a', 'b')",
                   "migrations.AlterField(model_name='thing', name='a', field=models.TextField())"):
            self.assertTrue(any("ممتاز" in e for e in errors(self.mig(op))), op)

    def test_privileged_marker_downgrades(self):
        root = make(migrations__0002_next=(
            "# ext: privileged-migration\nfrom django.db import migrations\nclass Migration(migrations.Migration):\n"
            "    dependencies = []\n    operations = [migrations.RunSQL('select 1')]\n"))
        self.assertEqual(errors(root), [])
        self.assertTrue([f for f in extcheck.check_plugin(root) if f.level == "warn"])

    def test_addfield_needs_null_or_default(self):
        op = "migrations.AddField(model_name='thing', name='n', field=models.IntegerField())"
        self.assertTrue(any("null" in e for e in errors(self.mig(op))))
        ok = "migrations.AddField(model_name='thing', name='n', field=models.IntegerField(default=0))"
        self.assertEqual(errors(self.mig(ok)), [])

    def test_foreign_dependency_forbidden(self):
        self.assertTrue(any("billing" in e for e in errors(self.mig("", '("billing", "0001_initial")'))))

    def test_db_table_in_options(self):
        op = "migrations.CreateModel(name='T', fields=[], options={'db_table': 'x'})"
        self.assertTrue(any("db_table" in e for e in errors(self.mig(op))))


class CommandTests(SimpleTestCase):
    def run_cmd(self, root, *args):
        out = StringIO()
        call_command("ext_check", *args, root=str(root), stdout=out)
        return out.getvalue()

    def test_empty_ext(self):
        self.assertIn("پلاگینی", self.run_cmd(tempfile.mkdtemp()))

    def test_good_and_bad(self):
        root = make().parent
        self.assertIn("سالم", self.run_cmd(root))
        (root / "demo" / "views.py").write_text("import subprocess\n")
        with self.assertRaises(CommandError):
            self.run_cmd(root)

    def test_unknown_plugin(self):
        with self.assertRaises(CommandError):
            self.run_cmd(make().parent, "nope")

    def test_real_ext_is_clean(self):
        call_command("ext_check", stdout=StringIO())
