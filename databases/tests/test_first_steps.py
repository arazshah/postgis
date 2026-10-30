from django.urls import reverse

from databases import services
from jobs.models import Job

from .test_services import BaseCase


class FirstStepsCardTests(BaseCase):
    """پایگاه تازه خالی است؛ نمای کلی تا اولین ورود داده‌ی موفق راه بعدی را نشان می‌دهد."""

    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, "fresh", "Abcdefgh1234", [])
        self.client.force_login(self.user)
        self.url = reverse("databases:detail", args=[self.db.pk])

    def page(self):
        return self.client.get(self.url).content.decode()

    def test_empty_database_shows_next_steps_with_ready_data_first(self):
        html = self.page()
        self.assertIn("first-steps", html)
        self.assertIn(reverse("iranmap:ready", args=[self.db.pk]), html)
        self.assertIn(reverse("databases:import", args=[self.db.pk]), html)
        self.assertIn("حالا داده بگذارید", html)

    def test_running_import_changes_the_message(self):
        Job.objects.create(kind=Job.Kind.OSM_IMPORT, status=Job.Status.RUNNING, database=self.db, user=self.user)
        html = self.page()
        self.assertIn("ورود داده در حال انجام است", html)
        self.assertNotIn("حالا داده بگذارید", html)

    def test_card_disappears_after_first_successful_import(self):
        Job.objects.create(kind=Job.Kind.IMPORT, status=Job.Status.DONE, database=self.db, user=self.user)
        self.assertNotIn("first-steps", self.page())

    def test_failed_import_does_not_hide_the_card(self):
        Job.objects.create(kind=Job.Kind.IMPORT, status=Job.Status.FAILED, database=self.db, user=self.user)
        self.assertIn("حالا داده بگذارید", self.page())
