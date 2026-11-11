"""پاک‌سازی ورودهای نیمه‌کاره: کار دوره‌ای پلاگین پایگاه داده، نه صف کارها."""
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from databases import services
from databases.jobs import expire_import_drafts, import_dir
from databases.tests.test_services import BaseCase
from jobs.models import Job


class ExpireImportDraftsTests(BaseCase):
    def test_old_drafts_expire_and_their_folder_goes_away(self):
        import tempfile

        with tempfile.TemporaryDirectory() as root, override_settings(IMPORT_ROOT=root):
            db = services.create_database(self.user, "draftdb", "Abcdefgh123", ["postgis"])
            old = Job.objects.create(kind=Job.Kind.IMPORT, status=Job.Status.DRAFT, database=db, user=self.user)
            fresh = Job.objects.create(kind=Job.Kind.IMPORT, status=Job.Status.DRAFT, database=db, user=self.user)
            Job.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))
            folder = import_dir(old)
            folder.mkdir(parents=True)
            (folder / "a.geojson").write_text("{}")
            old.refresh_from_db()
            self.assertEqual(expire_import_drafts(), 1)
            old.refresh_from_db()
            fresh.refresh_from_db()
            self.assertEqual((old.status, fresh.status), (Job.Status.EXPIRED, Job.Status.DRAFT))
            self.assertFalse(folder.exists())
