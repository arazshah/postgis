"""ابزارهای افزوده: ساخت SQL و اعتبارسنجی (بدون PostgreSQL) و اجرای واقعی روی PostGIS (با TEST_PG_HOST)."""
import os
import unittest
from unittest import mock

from django.test import SimpleTestCase

from databases.explorer import TableRef
from tools import engine as tools

PG_HOST = os.environ.get("TEST_PG_HOST", "")


def _t(name, gtype, schema="public", srid=4326):
    return TableRef(schema, name, 1, "r", geometry=[{"column": "geom", "type": gtype, "srid": srid, "geography": False}])


COLS = [{"name": "gid", "spatial": False, "base": "int4"}, {"name": "name", "spatial": False, "base": "text"},
        {"name": "geom", "spatial": True, "base": "geometry"}]
LAYERS = [_t("schools", "POINT"), _t("roads", "LINESTRING"), _t("zones", "POLYGON")]
ROUTING = [TableRef("routing", "ways", 1, "r", geometry=[{"column": "the_geom", "type": "LINESTRING", "srid": 4326}]),
           TableRef("routing", "ways_vertices_pgr", 1, "r", geometry=[{"column": "the_geom", "type": "POINT", "srid": 4326}])]


class PrepareTests(SimpleTestCase):
    def prep(self, key, layers=None, **p):
        ex = mock.Mock()
        ex.tables.return_value = LAYERS if layers is None else layers
        ex.columns.return_value = COLS
        p.setdefault("output", "out_t")
        with mock.patch("kernel.tenantdb.catalog", return_value=ex):
            return tools._prepare(None, key, p)

    def render(self, composed):
        return composed.as_string(None) if hasattr(composed, "as_string") else str(composed)

    def test_every_new_tool_builds_a_select(self):
        net = LAYERS + ROUTING
        cases = [
            ("within", LAYERS, dict(layer="public.schools", other="public.roads", distance="300")),
            ("voronoi", LAYERS, dict(layer="public.schools")),
            ("voronoi", LAYERS, dict(layer="public.schools", other="public.zones")),
            ("cluster", LAYERS, dict(layer="public.schools", distance="200", minpoints="5")),
            ("measure", LAYERS, dict(layer="public.zones", other="public.roads", mode="length")),
            ("measure", LAYERS, dict(layer="public.zones", other="public.zones", mode="area")),
            ("clip", LAYERS, dict(layer="public.roads", other="public.zones")),
            ("erase", LAYERS, dict(layer="public.zones", other="public.zones")),
            ("route", net, dict(lon="51.3", lat="35.7", lon2="51.4", lat2="35.8")),
            ("netnearest", net, dict(layer="public.schools", other="public.schools", distance="5000")),
            ("coverage", net, dict(layer="public.schools", distance="800")),
        ]
        for key, layers, p in cases:
            with self.subTest(key=key, p=p):
                body = self.prep(key, layers, **p)[3]
                self.assertTrue(body)

    def test_network_tools_need_routing_tables(self):
        for key, p in (("route", dict(lon="1", lat="1", lon2="2", lat2="2")),
                       ("netnearest", dict(layer="public.schools", other="public.schools")),
                       ("coverage", dict(layer="public.schools", distance="800"))):
            with self.subTest(key=key), self.assertRaisesMessage(tools.ToolError, "شبکه معابر"):
                self.prep(key, **p)

    def test_geometry_type_and_range_errors(self):
        with self.assertRaisesMessage(tools.ToolError, "POINT"):
            self.prep("cluster", layer="public.zones", distance="200", minpoints="5")
        with self.assertRaisesMessage(tools.ToolError, "POLYGON"):
            self.prep("clip", layer="public.roads", other="public.roads")
        with self.assertRaisesMessage(tools.ToolError, "LINE"):
            self.prep("measure", layer="public.zones", other="public.zones", mode="length")
        with self.assertRaisesMessage(tools.ToolError, "بین"):
            self.prep("cluster", layer="public.schools", distance="200", minpoints="1")
        with self.assertRaisesMessage(tools.ToolError, "بین"):
            self.prep("within", layer="public.schools", other="public.roads", distance="0")

    def test_guards_cap_network_and_voronoi_inputs(self):
        net = LAYERS + ROUTING
        self.assertEqual(len(self.prep("coverage", net, layer="public.schools", distance="800")[4]), 1)
        self.assertEqual(len(self.prep("netnearest", net, layer="public.schools", other="public.schools", distance="5000")[4]), 2)
        self.assertEqual(len(self.prep("voronoi", layer="public.schools")[4]), 1)

    def test_summary_mentions_route_and_measure(self):
        s = tools.summarize(None, "route", dict(lon="51.3", lat="35.7", lon2="51.4", lat2="35.8"))
        self.assertIn("از 51.3, 35.7", s)
        self.assertIn("تا 51.4, 35.8", s)
        self.assertIn("مساحت", tools.summarize(None, "measure", dict(layer="public.z", mode="area")))


@unittest.skipUnless(PG_HOST, "TEST_PG_HOST تنظیم نشده")
class RealPostgisTests(unittest.TestCase):
    """SQL هر ابزار روی PostGIS و pgRouting واقعی (افزونه‌ها باید در پایگاه آزمون ساخته‌شدنی باشند)."""

    @classmethod
    def setUpClass(cls):
        import psycopg

        cls.kw = dict(host=PG_HOST, port=int(os.environ.get("TEST_PG_PORT", "5432")), user=os.environ.get("TEST_PG_USER", "postgres"),
                      password=os.environ.get("TEST_PG_PASSWORD", "postgres"))
        with psycopg.connect(dbname="postgres", autocommit=True, **cls.kw) as c:
            c.execute("DROP DATABASE IF EXISTS newtools_t")
            c.execute("CREATE DATABASE newtools_t")
        cls.conn = psycopg.connect(dbname="newtools_t", **cls.kw)
        try:
            cls.conn.execute("CREATE EXTENSION postgis")
            cls.conn.execute("CREATE EXTENSION pgrouting")
        except psycopg.Error as exc:
            cls.conn.close()
            raise unittest.SkipTest(f"PostGIS/pgRouting نصب نیست: {exc}") from exc
        cls.conn.execute("""
          CREATE TABLE schools(gid serial PRIMARY KEY, name text, geom geometry(Point,4326));
          INSERT INTO schools(name, geom) SELECT 's'||i, ST_SetSRID(ST_MakePoint(51.30+(i%10)*0.005, 35.70+(i/10)*0.005),4326)
            FROM generate_series(1,40) i;
          CREATE TABLE clinics(gid serial PRIMARY KEY, name text, geom geometry(Point,4326));
          INSERT INTO clinics(name, geom) VALUES ('c1', ST_SetSRID(ST_MakePoint(51.30,35.70),4326));
          CREATE TABLE zone(gid serial PRIMARY KEY, name text, geom geometry(Polygon,4326));
          INSERT INTO zone(name, geom) VALUES ('z', ST_SetSRID(ST_MakeEnvelope(51.29,35.69,51.33,35.72),4326));
          CREATE TABLE roads(gid serial PRIMARY KEY, name text, geom geometry(LineString,4326));
          INSERT INTO roads(name, geom) VALUES ('r', ST_SetSRID(ST_MakeLine(ST_MakePoint(51.28,35.70),ST_MakePoint(51.40,35.70)),4326));
          CREATE SCHEMA routing;
          CREATE TABLE routing.ways(gid serial PRIMARY KEY, source bigint, target bigint, length_m float8, cost float8,
                                    reverse_cost float8, the_geom geometry(LineString,4326));
          INSERT INTO routing.ways(the_geom, length_m, cost, reverse_cost)
            SELECT g, ST_Length(g::geography), 1, 1 FROM (
              SELECT ST_MakeLine(ST_MakePoint(51.29+i*0.005,35.69+j*0.005),ST_MakePoint(51.29+(i+1)*0.005,35.69+j*0.005)) g
                FROM generate_series(0,9) i, generate_series(0,9) j
              UNION ALL SELECT ST_MakeLine(ST_MakePoint(51.29+i*0.005,35.69+j*0.005),ST_MakePoint(51.29+i*0.005,35.69+(j+1)*0.005))
                FROM generate_series(0,10) i, generate_series(0,9) j) s;
          SELECT pgr_createTopology('routing.ways', 0.0001, 'the_geom', 'gid');
        """)
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def run_tool(self, key, **p):
        from databases import explorer as E

        conn = self.conn

        class Fake(E.Explorer):
            def __init__(self, db):
                pass

            def connect(self, read_only=True, as_owner=False):
                import psycopg

                c = psycopg.connect(dbname="newtools_t", **RealPostgisTests.kw)
                c.read_only = read_only
                return c

        p.setdefault("output", f"out_{key}")
        p["replace"] = "on"
        with mock.patch("kernel.tenantdb.catalog", Fake):
            _ex, out, target, body, guards = tools._prepare(None, key, p)
        for q, cap, _m in guards:
            self.assertLessEqual(conn.execute(q).fetchone()[0], cap)
        conn.execute(tools.sql.SQL("DROP TABLE IF EXISTS {}").format(target))
        conn.execute(tools.sql.SQL("CREATE TABLE {} AS {}").format(target, body))
        tools._fix_geom_type(conn, target)
        rows = conn.execute(tools.sql.SQL("SELECT to_jsonb(t) - 'geom' AS j, GeometryType(geom) FROM {} t").format(target)).fetchall()
        conn.commit()
        return rows

    def test_within_and_clip_and_erase(self):
        rows = self.run_tool("within", layer="public.schools", other="public.roads", distance="100")
        self.assertTrue(rows and all(r[0]["neighbor_count"] == 1 and r[1] == "POINT" for r in rows))
        clipped = self.run_tool("clip", layer="public.roads", other="public.zone")
        self.assertEqual([r[1] for r in clipped], ["LINESTRING"])
        left = self.run_tool("erase", layer="public.zone", other="public.zone")
        self.assertEqual(left, [])

    def test_voronoi_cluster_measure(self):
        cells = self.run_tool("voronoi", layer="public.schools")
        self.assertEqual(len(cells), 40)
        clipped = self.run_tool("voronoi", layer="public.schools", other="public.zone")
        self.assertTrue(0 < len(clipped) <= 40)
        self.assertLess(sum(r[0]["area_m2"] for r in clipped), sum(r[0]["area_m2"] for r in cells))
        cl = self.run_tool("cluster", layer="public.schools", distance="700", minpoints="3")
        self.assertEqual([r[0]["point_count"] for r in cl], [40])
        m = self.run_tool("measure", layer="public.zone", other="public.roads", mode="length")
        self.assertEqual(len(m), 1)
        self.assertGreater(m[0][0]["length_m"], 3000)
        a = self.run_tool("measure", layer="public.zone", other="public.zone", mode="area")
        self.assertEqual(float(a[0][0]["share_pct"]), 100.0)

    def test_network_tools(self):
        r = self.run_tool("route", lon="51.29", lat="35.69", lon2="51.34", lat2="35.74")
        self.assertEqual(r[0][1], "MULTILINESTRING")
        self.assertGreater(r[0][0]["distance_m"], 1000)
        n = self.run_tool("netnearest", layer="public.schools", other="public.clinics", label="name", distance="50000")
        self.assertEqual(len(n), 40)
        self.assertTrue(all(x[0]["nearest_name"] == "c1" and x[0]["network_m"] >= 0 for x in n))
        c = self.run_tool("coverage", layer="public.clinics", distance="600")
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0][1], "POLYGON")
