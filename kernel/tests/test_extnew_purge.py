"""مرحله‌ی ۵ سطح ۳: داربست ext_new و پاک‌سازی ext_purge."""
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase

from kernel import extcheck, extnew, extpurge


class ScaffoldTests(SimpleTestCase):
    def test_scaffold_passes_ext_check(self):
        root = Path(tempfile.mkdtemp())
        extnew.scaffold(root, "gps_live", "ردیابی GPS")
        errs = [str(f) for f in extcheck.check_plugin(root / "gps_live") if f.level == "error"]
        self.assertEqual(errs, [])

    def test_all_python_files_compile(self):
        root = Path(tempfile.mkdtemp())
        for f in extnew.scaffold(root, "demo", "نمونه"):
            if f.suffix == ".py":
                compile(f.read_text(), str(f), "exec")

    def test_rejects_bad_id_and_name_and_existing(self):
        root = Path(tempfile.mkdtemp())
        for bad in ("Bad", "x", "a-b", "1abc", "a" * 50):
            with self.assertRaises(extnew.ScaffoldError):
                extnew.scaffold(root, bad, "نام")
        for bad_name in ('نام"خراب', "نام{x}", "x" * 80, "a\nb"):
            with self.assertRaises(extnew.ScaffoldError):
                extnew.scaffold(root, "okid", bad_name)
        extnew.scaffold(root, "okid", "نام")
        with self.assertRaises(extnew.ScaffoldError):
            extnew.scaffold(root, "okid", "نام")

    def test_command(self):
        root = tempfile.mkdtemp()
        out = StringIO()
        call_command("ext_new", "my_plug", name="نمونه", root=root, stdout=out)
        self.assertIn("فایل", out.getvalue())
        with self.assertRaises(CommandError):
            call_command("ext_new", "my_plug", root=root)


class PurgeTests(TestCase):
    def mk(self, *tables, apps=()):
        with connection.cursor() as cur:
            for t in tables:
                cur.execute(f'CREATE TABLE "{t}" (id int)')
            for a in apps:
                cur.execute("INSERT INTO django_migrations (app, name, applied) VALUES (%s, '0001_initial', now())", [a])

    def exists(self, t):
        return t in connection.introspection.table_names()

    def test_preview_changes_nothing_and_yes_purges_only_its_tables(self):
        self.mk("x_gone_note", "x_gone_tag", "x_other_note", "databases_userdatabase_copy", apps=["x_gone", "x_other"])
        empty = Path(tempfile.mkdtemp())
        out = StringIO()
        call_command("ext_purge", "gone", root=str(empty), stdout=out)
        self.assertTrue(self.exists("x_gone_note"))
        call_command("ext_purge", "gone", yes=True, root=str(empty), stdout=out)
        self.assertFalse(self.exists("x_gone_note") or self.exists("x_gone_tag"))
        self.assertTrue(self.exists("x_other_note"))
        self.assertTrue(self.exists("databases_userdatabase_copy"))
        with connection.cursor() as cur:
            cur.execute("SELECT app FROM django_migrations WHERE app IN ('x_gone','x_other')")
            self.assertEqual([r[0] for r in cur.fetchall()], ["x_other"])

    def test_refuses_while_installed(self):
        self.mk("x_live_note", apps=["x_live"])
        root = Path(tempfile.mkdtemp())
        (root / "live").mkdir()
        with self.assertRaises(CommandError):
            call_command("ext_purge", "live", yes=True, root=str(root))
        self.assertTrue(self.exists("x_live_note"))

    def test_refuses_prefix_overlap(self):
        self.mk("x_a_note", "x_a_b_note", apps=["x_a", "x_a_b"])
        with self.assertRaises(CommandError):
            call_command("ext_purge", "a", yes=True, root=tempfile.mkdtemp())
        self.assertTrue(self.exists("x_a_b_note") and self.exists("x_a_note"))

    def test_nothing_to_purge_and_bad_id(self):
        for pid in ("never_existed", "Bad;drop"):
            with self.assertRaises(CommandError):
                call_command("ext_purge", pid, yes=True, root=tempfile.mkdtemp())

    def test_plan_rejects_plugin_in_registry(self):
        from kernel.plugins import registry

        registry.register("zz_reg", "x", kind="custom", tier=3)
        self.addCleanup(registry.remove_plugin, "zz_reg")
        with self.assertRaises(extpurge.PurgeError):
            extpurge.plan("zz_reg", Path(tempfile.mkdtemp()))
