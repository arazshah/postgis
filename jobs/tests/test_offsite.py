import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from core.admin import SiteSettingsForm
from core.models import SiteSettings
from databases.models import DatabaseServer, Plan, UserDatabase
from jobs import offsite
from jobs.models import Job


class FakeS3:
    """جایگزین کلاینت boto3: فایل‌ها را در یک دیکشنری نگه می‌دارد."""

    def __init__(self):
        self.objects = {}

    def upload_file(self, filename, bucket, key):
        self.objects[(bucket, key)] = Path(filename).read_bytes()

    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[(bucket, key)])

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        import io

        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


class OffsiteBase(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        o = override_settings(BACKUP_ROOT=self.tmp.name)
        o.enable()
        self.addCleanup(o.disable)
        self.s3 = FakeS3()
        p = mock.patch("jobs.offsite._client", return_value=self.s3)
        p.start()
        self.addCleanup(p.stop)
        self.conf = SiteSettings.get()
        self.conf.offsite_enabled = True
        self.conf.offsite_endpoint = "https://s3.example.ir"
        self.conf.offsite_bucket = "PostGIS_bucket"
        self.conf.set_offsite_keys("AK", "SK")
        self.conf.save()
        server = DatabaseServer(name="s1", host="10.0.0.5", public_host="db.postgis.ir", is_default=True)
        server.set_admin_password("x")
        server.save()
        self.user = User.objects.create_user("09120000077")
        self.db = UserDatabase.objects.create(owner=self.user, server=server, plan=Plan.objects.get(slug="free"),
                                              label="t", db_name="gp_t", role_name="gp_t_user",
                                              status=UserDatabase.Status.ACTIVE)

    def make_backup(self, data=b"PGDMP-fake-dump" * 1000, **kw):
        rel = Path(str(self.db.pk)) / "gp_t-1-auto.dump"
        path = Path(self.tmp.name) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return Job.objects.create(kind=Job.Kind.BACKUP, status=Job.Status.DONE, trigger=Job.Trigger.AUTO,
                                  database=self.db, file=str(rel), size_bytes=len(data),
                                  expires_at=timezone.now() + timedelta(days=3), **kw)


class CryptoTests(TestCase):
    def roundtrip(self, data):
        with tempfile.TemporaryDirectory() as d:
            a, b, c = Path(d, "a"), Path(d, "b"), Path(d, "c")
            a.write_bytes(data)
            offsite.encrypt_file(a, b)
            self.assertNotIn(data[:32], b.read_bytes()) if len(data) >= 32 else None
            offsite.decrypt_file(b, c)
            self.assertEqual(c.read_bytes(), data)
            return b.read_bytes()

    def test_roundtrip_sizes(self):
        for n in (1, 100, offsite.CHUNK - 1, offsite.CHUNK, offsite.CHUNK + 1, 3 * offsite.CHUNK + 7):
            self.roundtrip(b"x" * n)

    def test_tamper_and_truncation_detected(self):
        with tempfile.TemporaryDirectory() as d:
            a, b, c = Path(d, "a"), Path(d, "b"), Path(d, "c")
            a.write_bytes(b"y" * (2 * offsite.CHUNK + 5))
            offsite.encrypt_file(a, b)
            raw = b.read_bytes()
            bad = bytearray(raw)
            bad[100] ^= 1
            b.write_bytes(bytes(bad))
            with self.assertRaises(offsite.OffsiteError):
                offsite.decrypt_file(b, c)
            # قطع‌کردن آخر فایل (حذف آخرین قطعه) هم باید پیدا شود
            first_len = int.from_bytes(raw[22:26], "big")
            b.write_bytes(raw[: 22 + 4 + first_len])
            with self.assertRaises(offsite.OffsiteError):
                offsite.decrypt_file(b, c)

    def test_wrong_key_fails(self):
        blob = self.roundtrip(b"secret data")
        with tempfile.TemporaryDirectory() as d, override_settings(CREDENTIALS_ENCRYPTION_KEY="another-key-entirely"):
            Path(d, "in").write_bytes(blob)
            with self.assertRaises(offsite.OffsiteError):
                offsite.decrypt_file(Path(d, "in"), Path(d, "out"))

    def test_not_our_format(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "x").write_bytes(b"hello world, definitely not encrypted")
            with self.assertRaises(offsite.OffsiteError):
                offsite.decrypt_file(Path(d, "x"), Path(d, "y"))

    def test_fingerprint_stable_and_key_dependent(self):
        a = offsite.key_fingerprint()
        self.assertEqual(a, offsite.key_fingerprint())
        with override_settings(CREDENTIALS_ENCRYPTION_KEY="other"):
            self.assertNotEqual(a, offsite.key_fingerprint())


class UploadTests(OffsiteBase):
    def test_upload_encrypted_then_restore_from_remote(self):
        job = self.make_backup()
        self.assertTrue(offsite.upload_job(job))
        job.save()
        self.assertTrue(job.offsite_key.endswith(".dump.enc"))
        self.assertTrue(job.offsite_encrypted)
        stored = self.s3.objects[("PostGIS_bucket", job.offsite_key)]
        self.assertNotIn(b"PGDMP-fake-dump", stored)
        self.assertFalse(list(Path(self.tmp.name).glob("offsite-*")), "فایل موقت باید پاک شود")
        # فایل محلی گم می‌شود، از نسخه‌ی ابری برمی‌گردد
        original = job.path.read_bytes()
        job.path.unlink()
        path = offsite.ensure_local(job)
        self.assertEqual(path.read_bytes(), original)

    def test_plain_upload_when_encryption_off(self):
        self.conf.offsite_encrypt = False
        self.conf.save()
        job = self.make_backup()
        self.assertTrue(offsite.upload_job(job))
        self.assertTrue(job.offsite_key.endswith(".dump"))
        self.assertEqual(self.s3.objects[("PostGIS_bucket", job.offsite_key)], job.path.read_bytes())

    def test_failure_is_recorded_not_raised(self):
        job = self.make_backup()
        with mock.patch.object(self.s3, "upload_file", side_effect=RuntimeError("timeout reached")):
            self.assertFalse(offsite.upload_job(job))
        self.assertIn("timeout", job.offsite_error)
        self.assertEqual(job.offsite_key, "")
        self.assertFalse(list(Path(self.tmp.name).glob("offsite-*")))

    def test_disabled_does_nothing(self):
        self.conf.offsite_enabled = False
        self.conf.save()
        job = self.make_backup()
        self.assertFalse(offsite.upload_job(job))
        self.assertEqual(self.s3.objects, {})

    def test_ensure_local_without_remote_returns_none(self):
        job = self.make_backup()
        job.path.unlink()
        self.assertIsNone(offsite.ensure_local(job))

    def test_ensure_local_reports_wrong_key_as_none(self):
        job = self.make_backup()
        offsite.upload_job(job)
        job.path.unlink()
        with override_settings(CREDENTIALS_ENCRYPTION_KEY="rotated"):
            self.assertIsNone(offsite.ensure_local(job))
        self.assertFalse(job.path.exists())

    def test_retry_pending_uploads_missed_backups(self):
        job = self.make_backup()
        n = offsite.retry_pending()
        job.refresh_from_db()
        self.assertEqual(n, 1)
        self.assertTrue(job.offsite_key)

    def test_expired_backup_is_deleted_remotely(self):
        job = self.make_backup()
        offsite.upload_job(job)
        job.save()
        self.assertEqual(len(self.s3.objects), 1)
        job.expires_at = timezone.now() - timedelta(minutes=1)
        job.save()
        from jobs import services

        services.cleanup()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.EXPIRED)
        self.assertEqual(job.offsite_key, "")
        self.assertEqual(self.s3.objects, {})

    def test_remote_delete_failure_retried_later(self):
        job = self.make_backup()
        offsite.upload_job(job)
        job.status = Job.Status.EXPIRED
        job.save()
        with mock.patch.object(self.s3, "delete_object", side_effect=RuntimeError("down")):
            self.assertEqual(offsite.purge_expired(), 0)
        job.refresh_from_db()
        self.assertTrue(job.offsite_key)
        self.assertEqual(offsite.purge_expired(), 1)

    def test_connection_test(self):
        self.assertIn("درست", offsite.test_connection(self.conf))
        self.assertEqual(self.s3.objects, {})
        with mock.patch.object(self.s3, "put_object", side_effect=RuntimeError("AccessDenied")):
            with self.assertRaises(offsite.OffsiteError):
                offsite.test_connection(self.conf)

    def test_do_backup_survives_upload_failure(self):
        from jobs import services

        job = Job.objects.create(kind=Job.Kind.BACKUP, trigger=Job.Trigger.AUTO, database=self.db,
                                 status=Job.Status.RUNNING)

        def fake_dump(db, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"dump")
            return 4

        with mock.patch.object(services, "dump_database", fake_dump), \
                mock.patch.object(self.s3, "upload_file", side_effect=RuntimeError("down")):
            services.run(job)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.DONE)
        self.assertTrue(job.offsite_error)

    def test_restore_uses_remote_copy_when_local_missing(self):
        from jobs import services

        src = self.make_backup()
        offsite.upload_job(src)
        src.save()
        src.path.unlink()
        job = Job.objects.create(kind=Job.Kind.RESTORE, database=self.db, source=src, status=Job.Status.RUNNING)
        seen = {}

        def fake_restore_into(server, scratch, dump):
            seen["exists"] = Path(dump).exists()
            raise services.JobError("stop here")

        prov = mock.MagicMock()
        with mock.patch.object(services, "restore_into", fake_restore_into), \
                mock.patch("databases.provisioner.Provisioner.for_server", return_value=prov), \
                mock.patch.object(services, "run_inline", side_effect=lambda j: setattr(j, "status", Job.Status.DONE)):
            with self.assertRaises(services.JobError):
                services._do_restore(job)
        self.assertTrue(seen["exists"])


class AdminFormTests(TestCase):
    def form(self, **extra):
        from core.tests.test_footer_enamad import form_data

        conf = SiteSettings.get()
        return SiteSettingsForm(form_data(conf, **extra), instance=conf)

    def test_enabling_requires_endpoint_bucket_and_keys(self):
        f = self.form(offsite_enabled="on", offsite_endpoint="", offsite_bucket="b")
        self.assertFalse(f.is_valid())
        f = self.form(offsite_enabled="on", offsite_endpoint="https://s3.example.ir", offsite_bucket="PostGIS_bucket")
        self.assertFalse(f.is_valid())
        self.assertIn("offsite_enabled", f.errors)
        f = self.form(offsite_enabled="on", offsite_endpoint="https://s3.example.ir", offsite_bucket="PostGIS_bucket",
                      offsite_access_key="AK", offsite_secret_key="SK")
        self.assertTrue(f.is_valid(), f.errors)

    def test_endpoint_must_be_https_domain(self):
        for bad in ("http://s3.example.ir", "https://x/../y", "ftp://x", "https://10.0.0.1:9000/path?x=1"):
            self.assertFalse(self.form(offsite_endpoint=bad).is_valid(), bad)
        self.assertTrue(self.form(offsite_endpoint="https://s3.example.ir/").is_valid())

    def test_keys_are_encrypted_never_shown_and_kept_when_blank(self):
        f = self.form(offsite_access_key="AK123", offsite_secret_key="SK456")
        self.assertTrue(f.is_valid(), f.errors)
        f.save()
        conf = SiteSettings.get()
        self.assertNotIn("AK123", conf.offsite_access_key_encrypted)
        self.assertEqual(conf.get_offsite_keys(), ("AK123", "SK456"))
        # ذخیره‌ی دوباره بدون کلید: کلیدها نمی‌پرند
        f2 = self.form(offsite_bucket="PostGIS_bucket")
        self.assertTrue(f2.is_valid(), f2.errors)
        f2.save()
        self.assertEqual(SiteSettings.get().get_offsite_keys(), ("AK123", "SK456"))
        html = str(self.form()["offsite_secret_key"])
        self.assertNotIn("SK456", html)
        # حذف
        f3 = self.form(clear_offsite_keys="on")
        self.assertTrue(f3.is_valid(), f3.errors)
        f3.save()
        conf = SiteSettings.get()
        self.assertFalse(conf.has_offsite_keys)
        self.assertFalse(conf.offsite_enabled)

    def test_bad_bucket_name_rejected(self):
        self.assertFalse(self.form(offsite_bucket="bad bucket!").is_valid())
