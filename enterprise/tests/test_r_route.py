"""مسیر `/r/<کد>/`: نمای رستر نباید زیر لینک کوتاه پیامک بازگشت (winback) بماند."""
import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from databases.models import DatabaseServer, Plan, UserDatabase
from enterprise.models import Raster
from winback.models import Batch, Message, Route


class RouteTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        o = override_settings(RASTER_ROOT=str(self.tmp))
        o.enable()
        self.addCleanup(o.disable)
        srv = DatabaseServer(name="s", host="10.0.0.9", public_host="db.postgis.ir", is_default=True)
        srv.set_admin_password("x")
        srv.save()
        self.user = User.objects.create_user("09120000093")
        self.db = UserDatabase.objects.create(owner=self.user, server=srv, plan=Plan.objects.get(slug="free"), label="r", db_name="gp_r",
                                              role_name="gp_r_u", status=UserDatabase.Status.ACTIVE)

    def raster(self, **kw) -> Raster:
        vals = dict(database=self.db, title="رنگ طبیعی", status=Raster.Status.READY, bounds=[51.0, 35.0, 51.1, 35.1], width=10, height=10,
                    bands=3, dtype="Byte", rgb=True, created_by=self.user)
        vals.update(kw)
        return Raster.objects.create(**vals)

    def test_raster_view_opens_for_the_owner_and_the_public_link(self):
        r = self.raster()
        url = reverse("enterprise:raster_view", args=[r.slug])
        self.assertEqual(url, f"/r/{r.slug}/")
        self.assertEqual(self.client.get(url).status_code, 404)                 # خصوصی و ناشناس
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 200)                 # صاحب
        self.client.logout()
        Raster.objects.filter(pk=r.pk).update(is_public=True)
        self.assertEqual(self.client.get(url).status_code, 200)                 # عمومی برای همه

    def test_winback_code_still_wins_and_unknown_is_404(self):
        u = User.objects.create_user("09120000094")
        from winback import services
        services.sync_routes()
        batch = Batch.objects.create(route=Route.objects.get(key="no_database"))
        m = Message.objects.create(batch=batch, user=u, route_key="no_database", phone=u.phone, status="sent")
        r = self.client.get(f"/r/{m.code}/")
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("accounts:login"), r["Location"])
        self.assertEqual(self.client.get("/r/zzzzzzzz/").status_code, 404)

    def test_other_winback_paths_are_untouched(self):
        self.assertEqual(self.client.get("/r/invite/nope/").status_code, 302)   # دعوت (برنامه خاموش): به ورود، نه رستر
        self.assertEqual(self.client.get("/r/stop/nope/").status_code, 404)
        self.assertEqual(self.client.get("/r/nope/stop/").status_code, 404)

    def test_satellite_card_link_points_at_a_working_page(self):
        from satellite.models import SatRequest
        r = self.raster(is_public=True)
        req = SatRequest.objects.create(database=self.db, user=self.user, product="true_color", scene_id="S2A_X_1", bbox=[51.0, 35.0, 51.1, 35.1],
                                        status=SatRequest.Status.READY, raster=r)
        self.client.force_login(self.user)
        html = self.client.get(reverse("satellite:cards", args=[self.db.pk])).content.decode()
        self.assertIn(f"/r/{r.slug}/", html)
        self.assertEqual(self.client.get(f"/r/{r.slug}/").status_code, 200)
        self.assertTrue(req.pk)
