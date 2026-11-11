"""بسته‌ی پلاگین: امضا، خواندن امن zip، خط لوله‌ی بررسی، فعال‌سازی، بارگذاری در رجیستری و رابط مدیریت."""
import base64
import io
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from kernel import entitlements, pagekit, pkg
from kernel.models import PluginRelease, PluginState
from kernel.plugins import registry

PRIV = Ed25519PrivateKey.generate()
OTHER = Ed25519PrivateKey.generate()


def pub_line(name, key):
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return f"{name}={base64.b64encode(raw).decode()}"


KEYS = override_settings(PLUGIN_PUBLISHER_KEYS=pub_line("acme", PRIV))

MANIFEST = b'''id = "fleet"
name = "\xd9\xbe\xd8\xa7\xdb\x8c\xd8\xb4 \xd9\x86\xd8\xa7\xd9\x88\xda\xaf\xd8\xa7\xd9\x86"
version = "1.0.0"
api = 1
kind = "custom"
requires = ["databases"]
[contributes]
pages = ["pages/live.toml"]
'''
PAGE = '''key = "live"
title = "پایش آنلاین"
icon = "pulse"
group = "data"
[[params]]
name = "t"
kind = "layer"
label = "جدول"
[[blocks]]
kind = "kpi"
title = "تعداد"
sql = "select count(*) from {t}"
'''.encode()


def files(**over):
    f = {"plugin.toml": MANIFEST, "pages/live.toml": PAGE}
    f.update(over)
    return {k: v for k, v in f.items() if v is not None}


def build(fs=None, key=PRIV, publisher="acme", signed=True):
    fs = dict(fs or files())
    if signed:
        fs[pkg.SIG_NAME] = pkg.sign(fs, key, publisher)
    return pkg.pack(fs)


class CryptoAndArchiveTests(SimpleTestCase):
    def test_sign_verify_roundtrip_and_tamper_detection(self):
        fs = files()
        fs[pkg.SIG_NAME] = pkg.sign(fs, PRIV, "acme")
        keys = pkg.parse_keys(pub_line("acme", PRIV))
        self.assertEqual(pkg.verify(fs, keys), "acme")
        bad = {**fs, "pages/live.toml": PAGE + b"\n# x"}
        with self.assertRaisesMessage(pkg.PackageError, "تغییر کرده"):
            pkg.verify(bad, keys)
        with self.assertRaisesMessage(pkg.PackageError, "مجاز نیست"):
            pkg.verify(fs, pkg.parse_keys(pub_line("other", PRIV)))
        with self.assertRaisesMessage(pkg.PackageError, "تغییر کرده"):
            pkg.verify(fs, pkg.parse_keys(pub_line("acme", OTHER)))
        with self.assertRaisesMessage(pkg.PackageError, "امضا ندارد"):
            pkg.verify(files(), keys)
        renamed = {"pages/other.toml" if k == "pages/live.toml" else k: v for k, v in fs.items()}
        with self.assertRaises(pkg.PackageError):
            pkg.verify(renamed, keys)  # مسیر هم در چکیده است

    def test_bad_key_lines(self):
        with self.assertRaises(pkg.PackageError):
            pkg.parse_keys("acme=not-base64!!")
        self.assertEqual(pkg.parse_keys(""), {})

    def test_archive_limits_and_names(self):
        def zipped(entries, **kw):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, data in entries:
                    zf.writestr(name, data)
            return buf.getvalue()

        cases = [
            (b"not a zip", "zip معتبر"),
            (zipped([]), "خالی"),
            (zipped([("../evil.toml", b"x")]), "مجاز نیست"),
            (zipped([("/abs.toml", b"x")]), "مجاز نیست"),
            (zipped([("pages/a.py", b"x")]), "مجاز نیست"),
            (zipped([("evil.py", b"x")]), "مجاز نیست"),
            (zipped([("pages/ok.toml", b"x" * (pkg.MAX_FILE + 1))]), "۲۰۰ کیلوبایت"),
            (zipped([("pages/ab.toml", b"x"), ("pages/ab.toml", b"y")]), "دوبار"),
            (zipped([(f"pages/p{i:02d}x.toml", b"x") for i in range(pkg.MAX_FILES + 1)]), "تعداد فایل"),
        ]
        for data, needle in cases:
            with self.subTest(needle=needle), self.assertRaises(pkg.PackageError) as cm:
                pkg.read_archive(data)
            self.assertIn(needle, str(cm.exception))
        with self.assertRaisesMessage(pkg.PackageError, "۲ مگابایت"):
            pkg.read_archive(b"0" * (pkg.MAX_TOTAL + 1))

    def test_symlink_entries_are_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zi = zipfile.ZipInfo("pages/link.toml")
            zi.external_attr = (0o120777) << 16
            zf.writestr(zi, "plugin.toml")
        with self.assertRaisesMessage(pkg.PackageError, "پیوند نمادین"):
            pkg.read_archive(buf.getvalue())

    def test_pack_is_deterministic(self):
        self.assertEqual(pkg.pack(files()), pkg.pack(dict(reversed(list(files().items())))))


@KEYS
class InspectTests(TestCase):
    def inspect(self, data):
        return pkg.inspect(data)

    def failed(self, data):
        ins = self.inspect(data)
        self.assertFalse(ins.ok)
        return [s for s in ins.steps if not s.ok][0]

    def test_good_package_passes_all_stages(self):
        ins = self.inspect(build())
        self.assertTrue(ins.ok, ins.report())
        self.assertEqual((ins.publisher, ins.manifest["id"], len(ins.pages)), ("acme", "fleet", 1))
        self.assertEqual(len(ins.steps), 5)

    def test_unsigned_untrusted_or_modified_never_reach_later_stages(self):
        self.assertEqual(self.failed(build(signed=False)).stage, "امضا و ناشر")
        self.assertEqual(self.failed(build(key=OTHER)).stage, "امضا و ناشر")
        self.assertEqual(self.failed(build(publisher="evil")).stage, "امضا و ناشر")
        self.assertEqual(len(self.inspect(build(signed=False)).steps), 2)  # بعد از شکست امضا متوقف می‌شود

    def test_manifest_rules(self):
        def mani(**kw):
            lines = {"id": '"fleet"', "name": '"x"', "version": '"1.0.0"', "api": "1", "kind": '"custom"', "tier": "1"}
            lines.update(kw)
            body = "\n".join(f"{k} = {v}" for k, v in lines.items() if v is not None)
            return (body + '\n[contributes]\npages = ["pages/live.toml"]\n').encode()

        cases = [
            ({"id": '"Bad-ID"'}, "شناسه"), ({"version": '"1.0"'}, "نسخه"), ({"name": '""'}, "نام"),
            ({"kind": '"system"'}, "سیستمی"), ({"api": "9"}, "قرارداد"), ({"tier": "2"}, "tier = 1"),
            ({"id": '"databases"'}, "برخورد"),
        ]
        for patch, needle in cases:
            with self.subTest(patch=patch):
                step = self.failed(build(files(**{"plugin.toml": mani(**patch)})))
                self.assertIn(needle, step.detail)
        self.assertIn("plugin.toml در بسته نیست", self.failed(build({"pages/live.toml": PAGE})).detail)
        self.assertIn("plugin.toml خوانده نشد", self.failed(build(files(**{"plugin.toml": b"id = = 1"}))).detail)

    def test_requires_must_exist(self):
        m = MANIFEST.replace(b'requires = ["databases"]', b'requires = ["nope_plugin"]')
        self.assertIn("مورد نیاز نصب نیستند", self.failed(build(files(**{"plugin.toml": m}))).detail)

    def test_page_rules(self):
        self.assertIn("یکی نیست", self.failed(build(files(**{"pages/extra.toml": PAGE}))).detail)
        bad = PAGE.replace(b'kind = "kpi"', b'kind = "bogus"')
        self.assertIn("pages/live.toml", self.failed(build(files(**{"pages/live.toml": bad}))).detail)
        dup = MANIFEST.replace(b'pages = ["pages/live.toml"]', b'pages = ["pages/live.toml", "pages/two.toml"]')
        self.assertIn("تکراری", self.failed(build(files(**{"plugin.toml": dup, "pages/two.toml": PAGE}))).detail)
        nopages = MANIFEST.replace(b'pages = ["pages/live.toml"]', b"pages = []")
        self.assertIn("دست‌کم یک صفحه", self.failed(build({"plugin.toml": nopages})).detail)

    def test_version_must_increase(self):
        user = User.objects.create_user("09120000011")
        pkg.submit(build(), user)
        self.assertIn("بالاتر", self.failed(build(files(**{"pages/live.toml": PAGE + b"\n# v"}))).detail)
        v2 = MANIFEST.replace(b'version = "1.0.0"', b'version = "1.1.0"')
        self.assertTrue(self.inspect(build(files(**{"plugin.toml": v2}))).ok)


@KEYS
class LifecycleTests(TestCase):
    def setUp(self):
        entitlements.invalidate()
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(self._unload)
        self.up = User.objects.create_user("09120000021")
        self.boss = User.objects.create_user("09120000022")

    def _unload(self):
        for pid in list(pkg._loaded):
            registry.remove_plugin(pid)
            pkg._loaded.pop(pid, None)

    def v(self, ver, extra=b""):
        m = MANIFEST.replace(b'version = "1.0.0"', f'version = "{ver}"'.encode())
        return build(files(**{"plugin.toml": m, "pages/live.toml": PAGE + extra}))

    def test_submit_records_reports_even_for_rejected_and_dedupes(self):
        rel = pkg.submit(build(), self.up)
        self.assertEqual((rel.status, rel.publisher, rel.plugin_id), ("checked", "acme", "fleet"))
        self.assertTrue(all(s["ok"] for s in rel.report))
        with self.assertRaisesMessage(pkg.PackageError, "پیش‌تر بارگذاری"):
            pkg.submit(build(), self.up)
        bad = pkg.submit(build(signed=False), self.up)
        self.assertEqual(bad.status, "rejected")
        self.assertFalse(bad.report[-1]["ok"])
        with self.assertRaisesMessage(pkg.PackageError, "۲ مگابایت"):
            pkg.submit(b"0" * (pkg.MAX_TOTAL + 1), self.up)

    def test_two_person_rule_and_override(self):
        rel = pkg.submit(build(), self.up)
        with self.assertRaisesMessage(pkg.PackageError, "دونفره"):
            pkg.activate(rel, self.up)
        with override_settings(PLUGIN_SELF_APPROVAL=True):
            self.assertEqual(pkg.can_approve(rel, self.up), "")
        pkg.activate(rel, self.boss)
        rel.refresh_from_db()
        self.assertEqual((rel.status, rel.approved_by), ("active", self.boss))

    def test_activation_creates_a_restricted_plugin_nobody_sees_until_granted(self):
        pkg.activate(pkg.submit(build(), self.up), self.boss)
        st = PluginState.objects.get(plugin_id="fleet")
        self.assertEqual((st.access, st.enabled), ("restricted", True))
        pkg.sync()
        self.assertIn("fleet", registry.plugins)
        self.assertIsNotNone(pagekit.get("fleet", "live"))
        entitlements.invalidate()
        self.assertFalse(entitlements.allowed("fleet", user=self.up))

    def test_sync_adds_swaps_and_removes_in_this_process(self):
        r1 = pkg.submit(self.v("1.0.0"), self.up)
        pkg.activate(r1, self.boss)
        self.assertEqual(pkg.sync(), 1)
        self.assertEqual(pkg.sync(), 0)  # بدون تغییر
        r2 = pkg.submit(self.v("1.1.0", b"\n# c"), self.up)
        pkg.activate(r2, self.boss)
        r1.refresh_from_db()
        r1.refresh_from_db()
        self.assertEqual((r1.status, r2.status), ("retired", "active"))
        self.assertEqual(pkg.sync(), 2)  # حذف قبلی + بار نسخه‌ی تازه
        self.assertEqual(registry.plugins["fleet"].version, "1.1.0")
        # بازگشت به نسخه‌ی قبل
        pkg.activate(r1, self.boss)
        pkg.sync()
        self.assertEqual(registry.plugins["fleet"].version, "1.0.0")
        pkg.deactivate(PluginRelease.objects.get(status="active"))
        pkg.sync()
        self.assertNotIn("fleet", registry.plugins)
        self.assertIsNone(pagekit.get("fleet", "live"))

    def test_only_one_active_release_per_plugin_is_enforced_by_the_database(self):
        r1 = pkg.submit(self.v("1.0.0"), self.up)
        pkg.activate(r1, self.boss)
        r2 = pkg.submit(self.v("1.1.0", b"\n# c"), self.up)
        r2.status = "active"
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            r2.save()

    def test_revoked_publisher_blocks_activation_and_loading(self):
        r = pkg.submit(build(), self.up)
        with override_settings(PLUGIN_PUBLISHER_KEYS=pub_line("acme", OTHER)):
            with self.assertRaisesMessage(pkg.PackageError, "بررسی دوباره"):
                pkg.activate(r, self.boss)
        pkg.activate(r, self.boss)
        with override_settings(PLUGIN_PUBLISHER_KEYS=""):
            self._unload()
            with self.assertLogs("kernel.pkg", "ERROR"):
                pkg.sync()
            self.assertNotIn("fleet", registry.plugins)
            self.assertIn("fleet", registry.errors)

    def test_package_cannot_shadow_a_builtin_plugin(self):
        r = pkg.submit(build(), self.up)
        r.plugin_id = "tools"
        r.save()
        PluginRelease.objects.filter(pk=r.pk).update(status="active")
        pkg.sync()
        self.assertIn("برخورد", registry.errors["tools"])
        self.assertEqual(registry.plugins["tools"].kind, "feature")
        registry.errors.pop("tools", None)

    def test_request_refreshes_registry_before_menu_is_built(self):
        pkg.activate(pkg.submit(build(), self.up), self.boss)
        self.assertNotIn("fleet", registry.plugins)
        entitlements.invalidate()
        entitlements.refresh()
        self.assertIn("fleet", registry.plugins)


@KEYS
class AdminTests(TestCase):
    def setUp(self):
        entitlements.invalidate()
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(lambda: [registry.remove_plugin(p) or pkg._loaded.pop(p, None) for p in list(pkg._loaded)])
        self.root = User.objects.create_admin("root1", "Str0ng-Admin-Pass")
        self.second = User.objects.create_admin("root2", "Str0ng-Admin-Pass")
        self.client.force_login(self.root)

    def upload(self, data, name="fleet-1.0.0.gpkgx"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return self.client.post(reverse("admin:kernel_pluginrelease_upload"), {"package": SimpleUploadedFile(name, data)}, follow=True)

    def test_upload_shows_report_and_activation_needs_a_second_admin(self):
        r = self.upload(build())
        self.assertContains(r, "بسته بررسی شد")
        self.assertContains(r, "امضا و ناشر")
        rel = PluginRelease.objects.get()
        url = reverse("admin:kernel_pluginrelease_changelist")
        r = self.client.post(url, {"action": "activate_selected", "_selected_action": [rel.pk]}, follow=True)
        self.assertContains(r, "دونفره")
        self.assertEqual(PluginRelease.objects.get().status, "checked")
        self.client.force_login(self.second)
        r = self.client.post(url, {"action": "activate_selected", "_selected_action": [rel.pk]}, follow=True)
        self.assertContains(r, "فعال شد")
        self.assertEqual(PluginRelease.objects.get().status, "active")
        self.assertEqual(PluginState.objects.get(plugin_id="fleet").access, "restricted")
        entitlements.refresh()
        self.assertIn("fleet", registry.plugins)

    def test_rejected_upload_is_listed_with_its_reason(self):
        r = self.upload(build(signed=False))
        self.assertContains(r, "رد شد")
        self.assertContains(r, "امضا ندارد")
        self.assertEqual(PluginRelease.objects.get().status, "rejected")
        again = self.client.post(reverse("admin:kernel_pluginrelease_changelist"),
                                 {"action": "activate_selected", "_selected_action": [PluginRelease.objects.get().pk]}, follow=True)
        self.assertContains(again, "فقط نسخه‌ی بررسی‌شده")

    def test_upload_requires_the_permission_and_history_is_permanent(self):
        from django.contrib.auth.models import Permission

        staff = User.objects.create_admin("staff1", "Str0ng-Admin-Pass")
        staff.is_superuser = False
        staff.save()
        staff.user_permissions.add(*Permission.objects.filter(codename__in=["view_pluginrelease"]))
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("admin:kernel_pluginrelease_upload")).status_code, 403)
        self.client.force_login(self.root)
        self.upload(build())
        rel = PluginRelease.objects.get()
        self.assertEqual(self.client.post(reverse("admin:kernel_pluginrelease_delete", args=[rel.pk]), {"post": "yes"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:kernel_pluginrelease_change", args=[rel.pk])).status_code, 200)

    def test_missing_publisher_keys_are_explained(self):
        with override_settings(PLUGIN_PUBLISHER_KEYS=""):
            self.assertContains(self.client.get(reverse("admin:kernel_pluginrelease_upload")), "هیچ ناشر مجازی")


class CommandTests(SimpleTestCase):
    def test_keygen_pack_check_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            key = d / "pub.key"
            out = io.StringIO()
            call_command("plugin_keygen", "acme", "--out", str(key), stdout=out)
            line = [x for x in out.getvalue().splitlines() if x.startswith("acme=")][0]
            self.assertEqual(oct(key.stat().st_mode & 0o777), "0o600")
            with self.assertRaises(CommandError):
                call_command("plugin_keygen", "acme", "--out", str(key))  # بازنویسی نمی‌شود
            src = d / "src"
            (src / "pages").mkdir(parents=True)
            (src / "plugin.toml").write_bytes(MANIFEST)
            (src / "pages" / "live.toml").write_bytes(PAGE)
            pkgfile = d / "fleet.gpkgx"
            with mock.patch("kernel.pkg._identity", return_value=True):
                call_command("plugin_pack", str(src), "--key", str(key), "--publisher", "acme", "--out", str(pkgfile), stdout=io.StringIO())
                with override_settings(PLUGIN_PUBLISHER_KEYS=line):
                    res = io.StringIO()
                    call_command("plugin_check", str(pkgfile), stdout=res)
                    self.assertIn("ناشر: acme", res.getvalue())
                with override_settings(PLUGIN_PUBLISHER_KEYS=pub_line("acme", OTHER)), self.assertRaises(CommandError):
                    call_command("plugin_check", str(pkgfile), stdout=io.StringIO())
            (src / "evil.py").write_text("x")
            with self.assertRaisesMessage(CommandError, "مجاز نیست"):
                call_command("plugin_pack", str(src), "--key", str(key), "--publisher", "acme", "--out", str(d / "e.gpkgx"))


@KEYS
class EndToEndPackageTests(TestCase):
    """از بسته‌ی امضاشده تا صفحه‌ی دیده‌شده برای مشتری مجاز، بدون هیچ تغییر در کد."""

    def setUp(self):
        from types import SimpleNamespace

        from databases import services as db_services
        from databases.models import DatabaseServer
        from databases.tests.test_services import FakeProvisioner
        from kernel.tests.test_pagekit import FakeConn, fake_connect

        entitlements.invalidate()
        self.addCleanup(entitlements.invalidate)
        self.addCleanup(lambda: [registry.remove_plugin(p) or pkg._loaded.pop(p, None) for p in list(pkg._loaded)])
        p = mock.patch.object(db_services, "provisioner_for", return_value=FakeProvisioner())
        p.start()
        self.addCleanup(p.stop)
        srv = DatabaseServer(name="s1", host="10.0.0.5", public_host="db.postgis.ir", is_default=True)
        srv.set_admin_password("x")
        srv.save()
        self.owner = User.objects.create_user("09120000031")
        self.other = User.objects.create_user("09120000032")
        self.db = db_services.create_database(self.owner, "pkgdb", "Abcdefgh123", ["postgis"])
        self.up, self.boss = User.objects.create_user("09120000033"), User.objects.create_user("09120000034")
        for target, val in (("kernel.tenantdb.connect", fake_connect(FakeConn((["count"], [(41,)])))),):
            m = mock.patch(target, val)
            m.start()
            self.addCleanup(m.stop)
        c = mock.patch("kernel.tenantdb.catalog")
        c.start().return_value.tables.return_value = [SimpleNamespace(schema="public", name="positions")]
        self.addCleanup(c.stop)
        self.url = reverse("kernel:page", args=[self.db.pk, "fleet", "live"])

    @override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                                 "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
    def test_signed_package_becomes_a_page_only_for_the_customer_who_has_a_grant(self):
        from kernel.models import Entitlement

        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 404)  # هنوز نصب نیست
        pkg.activate(pkg.submit(build(), self.up), self.boss)
        entitlements.invalidate()
        self.assertEqual(self.client.get(self.url).status_code, 404)  # نصب است ولی مجوزی داده نشده
        Entitlement.objects.create(state=PluginState.objects.get(plugin_id="fleet"), kind="workspace", subject=str(self.db.pk))
        r = self.client.get(self.url, {"t": "public.positions"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "پایش آنلاین")
        self.assertContains(r, "41")
        self.assertContains(self.client.get(reverse("databases:detail", args=[self.db.pk])), self.url)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)  # عضو این پایگاه نیست
        # برداشتن بسته: صفحه و منو ناپدید
        pkg.deactivate(PluginRelease.objects.get(status="active"))
        entitlements.invalidate()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertNotContains(self.client.get(reverse("databases:detail", args=[self.db.pk])), self.url)


class StrictNameTests(SimpleTestCase):
    def test_trailing_newline_tricks_are_rejected(self):
        for name in ("plugin.toml\n", "pages/live.toml\n", "SIGNATURE\n"):
            self.assertIsNone(pkg.NAME_RE.fullmatch(name), name)
        self.assertIsNone(pkg.VERSION_RE.fullmatch("1.0.0\n"))
        self.assertIsNone(pagekit.KEY_RE.fullmatch("live\n"))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("pages/live.toml\n", b"x")
        with self.assertRaises(pkg.PackageError):
            pkg.read_archive(buf.getvalue())
        from kernel.plugins import PluginError

        with self.assertRaises(PluginError):
            registry.register("fleet\n", "x", kind="custom")
