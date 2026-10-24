"""ساخت پروژه برداشت روی PostGIS واقعی (فقط وقتی TEST_PG_HOST تنظیم شده باشد)."""
import json
import os
import unittest
import uuid
from unittest import mock

import psycopg
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from accounts.models import User
from databases import services as db_services
from databases.explorer import Explorer
from databases.models import DatabaseServer
from databases.provisioner import Provisioner
from publish.models import ApiKey, Service
from restapi.models import ApiTable
from survey import ddl, services
from survey.models import SurveyProject

PG_HOST = os.environ.get("TEST_PG_HOST", "")


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST not set")
@override_settings(ALLOWED_HOSTS=["testserver"])
class ProjectPgTests(TestCase):
    def setUp(self):
        cache.clear()
        server = DatabaseServer(name="it", host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")),
                                admin_user=os.environ.get("TEST_PG_USER", "postgres"), sslmode="disable",
                                public_host="db.example", is_default=True)
        server.set_admin_password(os.environ.get("TEST_PG_PASSWORD", "postgres"))
        server.save()
        Provisioner.for_server(server).harden()
        self.owner = User.objects.create_user("09120000041")
        self.db = db_services.create_database(self.owner, f"sv_{uuid.uuid4().hex[:8]}", "Surv-Pass-123", ["postgis"])
        self.addCleanup(self._drop)
        plan = self.db.plan
        plan.survey_projects = 2
        plan.save()
        self.kw = dict(host=server.host, port=server.port, user=self.db.role_name, password="Surv-Pass-123",
                       dbname=self.db.db_name, autocommit=True)

    def _drop(self):
        self.db.refresh_from_db()
        if self.db.status != "deleted":
            db_services.delete_database(self.db)

    def _sql(self, q, args=None):
        with psycopg.connect(**self.kw) as c:
            return c.execute(q, args).fetchall()

    def test_create_makes_schema_and_tables_with_right_srid(self):
        p = services.create_project(self.db, self.owner, "کوی نمونه", 32639, "topo")
        rows = self._sql("SELECT f_table_name, srid, type FROM geometry_columns WHERE f_table_schema = %s "
                         "ORDER BY 1", (p.slug,))
        self.assertEqual([(r[0], r[1], r[2]) for r in rows], [
            ("control_points", 32639, "POINT"), ("lines", 32639, "LINESTRING"),
            ("points", 32639, "POINT"), ("polygons", 32639, "POLYGON")])
        self.assertEqual(self._sql(f'SELECT count(*) FROM "{p.slug}".codes')[0][0], 6)
        cols = {r[0] for r in self._sql("SELECT column_name FROM information_schema.columns WHERE table_schema = %s "
                                        "AND table_name = 'points'", (p.slug,))}
        for c in ("client_uuid", "fix_quality", "hdop", "acc_h", "std_e", "h_ellip", "h_ortho", "antenna_h",
                  "corr_age", "driver_id", "driver_version", "qc_flags", "deleted_at", "synced_at"):
            self.assertIn(c, cols)

    def test_two_projects_with_different_srids_coexist(self):
        a = services.create_project(self.db, self.owner, "الف", 32639)
        b = services.create_project(self.db, self.owner, "ب", 32640)
        self.assertNotEqual(a.slug, b.slug)
        self.assertEqual(self._sql("SELECT Find_SRID(%s, 'points', 'geom')", (a.slug,))[0][0], 32639)
        self.assertEqual(self._sql("SELECT Find_SRID(%s, 'points', 'geom')", (b.slug,))[0][0], 32640)

    def test_quota_unknown_srid_and_empty_name(self):
        services.create_project(self.db, self.owner, "یک", 4326)
        services.create_project(self.db, self.owner, "دو", 4326)
        with self.assertRaises(services.SurveyError):
            services.create_project(self.db, self.owner, "سه", 4326)
        services.archive_project(SurveyProject.objects.first())
        services.create_project(self.db, self.owner, "سه", 4326)  # بایگانی سهمیه را آزاد می‌کند
        self.db.plan.survey_projects = 9
        self.db.plan.save()
        for bad_name, bad_srid in (("", 4326), ("x", 99999)):
            with self.assertRaises(services.SurveyError):
                services.create_project(self.db, self.owner, bad_name, bad_srid)

    def test_plan_without_survey_is_refused(self):
        self.db.plan.survey_projects = 0
        self.db.plan.save()
        with self.assertRaises(services.SurveyError):
            services.create_project(self.db, self.owner, "x", 4326)

    def test_ddl_failure_leaves_nothing(self):
        with mock.patch.object(ddl, "create_schema", side_effect=psycopg.errors.UndefinedTable("boom")):
            with self.assertRaises(services.SurveyError):
                services.create_project(self.db, self.owner, "خراب", 4326)
        self.assertEqual(SurveyProject.objects.count(), 0)
        self.assertEqual(self._sql("SELECT count(*) FROM pg_namespace WHERE nspname LIKE 's\\_%'")[0][0], 0)

    def test_panel_failure_drops_the_schema(self):
        with mock.patch.object(SurveyProject.objects, "create", side_effect=RuntimeError("panel down")):
            with self.assertRaises(RuntimeError):
                services.create_project(self.db, self.owner, "پنل", 4326)
        self.assertEqual(self._sql("SELECT count(*) FROM pg_namespace WHERE nspname LIKE 's\\_%'")[0][0], 0)

    def test_explorer_lists_project_tables_and_rest_inserts_with_transform(self):
        p = services.create_project(self.db, self.owner, "نمونه", 32639)
        names = {t.qualified for t in Explorer(self.db).tables()}
        self.assertIn(f"{p.slug}.points", names)
        svc = Service.objects.create(database=self.db)
        ApiTable.objects.create(service=svc, schema=p.slug, table="points", can_insert=True)
        _k, wkey = ApiKey.issue(self.db, self.owner, "w", can_write=True)
        url = f"/rest/{svc.slug}/{p.slug}.points/"
        u = str(uuid.uuid4())
        feat = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [51.41, 35.72]},
                "properties": {"client_uuid": u, "pt_no": "1", "code": "GR", "fix_quality": 4, "hdop": 0.8,
                               "acc_h": 0.02, "h_ellip": 1190.5}}
        c = Client()
        h = {"HTTP_AUTHORIZATION": f"Bearer {wkey}"}
        r = c.post(url, json.dumps(feat), content_type="application/json", **h)
        self.assertEqual(r.status_code, 201, r.content)
        srid, x = self._sql(f'SELECT ST_SRID(geom), ST_X(ST_Transform(geom, 4326)) FROM "{p.slug}".points')[0]
        self.assertEqual(srid, 32639)
        self.assertAlmostEqual(x, 51.41, places=5)
        r = c.post(url, json.dumps(feat), content_type="application/json", **h)  # client_uuid تکراری
        self.assertGreaterEqual(r.status_code, 400)
        self.assertEqual(self._sql(f'SELECT count(*) FROM "{p.slug}".points')[0][0], 1)
