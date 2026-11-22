from unittest import mock

from django.urls import reverse

from accounts.models import User
from analysis.models import ToolRun
from databases import services
from databases.tests.test_services import BaseCase
from maps.models import WebMap


class LiveTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, "livegis", "Abcdefgh123", [])
        self.client.force_login(self.user)

    def test_create_project_and_open(self):
        response = self.client.post(reverse("live:projects", args=[self.db.pk]), {"title": "نقشه من"})
        project = WebMap.objects.get(database=self.db)
        self.assertRedirects(response, reverse("live:studio", args=[self.db.pk, project.pk]),
                             fetch_redirect_response=False)
        with mock.patch("live.views.maps.spatial_tables", return_value=[]):
            response = self.client.get(reverse("live:studio", args=[self.db.pk, project.pk]))
        self.assertContains(response, "PostGIS")
        self.assertContains(response, "نقشه من")

    def test_unrelated_user_cannot_open_or_read(self):
        project = WebMap.objects.create(database=self.db, title="private")
        self.client.force_login(User.objects.create_user("09120000002"))
        for name, args in [("live:projects", [self.db.pk]), ("live:studio", [self.db.pk, project.pk]),
                           ("live:table", [self.db.pk])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 404)
        self.assertEqual(self.client.post(reverse("live:tool", args=[self.db.pk]), {"key": "buffer"}).status_code, 404)

    def test_anonymous_redirected(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("live:index")).status_code, 302)

    def test_tool_uses_existing_queue(self):
        with mock.patch("tools.api.engine.validate", return_value="buffer_result"), \
                mock.patch("tools.api.engine.summarize", return_value="buffer"):
            url = reverse("live:tool", args=[self.db.pk])
            response = self.client.post(url, {"key": "buffer", "output": "buffer_result"})
            self.assertEqual(response.status_code, 200)
            run = ToolRun.objects.get(database=self.db)
            self.assertEqual(run.output_table, "buffer_result")
            self.assertEqual(self.client.get(response.json()["url"]).json()["status"], "queued")
            self.assertEqual(self.client.post(url, {"key": "buffer", "output": "buffer_result"}).status_code, 400)
