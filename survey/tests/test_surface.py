"""هسته سطح و منحنی میزان با پاسخ‌های تحلیلی."""
import math

from django.test import SimpleTestCase

from survey import surface


def plane(f, n=1, size=10.0):
    """شبکه n×n مربعی که هر خانه‌اش دو مثلث است روی سطح z=f(x,y)."""
    s = size / n
    tris = []
    for i in range(n):
        for j in range(n):
            p = [(i * s + dx, j * s + dy) for dx, dy in ((0, 0), (s, 0), (s, s), (0, s))]
            v = [(x, y, f(x, y)) for x, y in p]
            tris += [(v[0], v[1], v[2]), (v[0], v[2], v[3])]
    return tris


class ContourTests(SimpleTestCase):
    def test_plane_contours_are_straight_lines_at_exact_positions(self):
        tris = plane(lambda x, y: x, n=4)  # z = x
        cs = surface.contours(tris, 1.0)
        self.assertEqual(sorted({c["level"] for c in cs}), [float(k) for k in range(1, 11)])  # ۰ فقط لبه است و با قاعده z>=سطح خطی نمی‌سازد
        by = {c["level"]: c for c in cs}
        for lev in range(1, 10):
            c = by[float(lev)]
            self.assertFalse(c["closed"])
            self.assertTrue(all(abs(x - lev) < 1e-9 for x, _ in c["coords"]))
            ys = sorted(y for _, y in c["coords"])
            self.assertAlmostEqual(ys[0], 0.0)
            self.assertAlmostEqual(ys[-1], 10.0)
        # هر سطح یک خط پیوسته است، نه تکه‌تکه
        self.assertEqual(len([c for c in cs if c["level"] == 5.0]), 1)

    def test_cone_gives_closed_rings_with_correct_radius(self):
        tris = plane(lambda x, y: 10 - math.hypot(x - 5, y - 5), n=40)
        cs = [c for c in surface.contours(tris, 2.0, base=0.0) if c["level"] in (6.0, 8.0)]
        self.assertEqual(len(cs), 2)
        for c in cs:
            self.assertTrue(c["closed"])
            self.assertEqual(c["coords"][0], c["coords"][-1])
            r = 10 - c["level"]
            radii = [math.hypot(x - 5, y - 5) for x, y in c["coords"]]
            self.assertLess(max(abs(v - r) for v in radii), 0.06)

    def test_index_contours_and_base_offset(self):
        cs = surface.contours(plane(lambda x, y: x, 2), 1.0, base=0.5, index_every=5)
        self.assertEqual(sorted({c["level"] for c in cs}), [0.5 + k for k in range(0, 10)])
        self.assertEqual([c["level"] for c in cs if c["index"]], [0.5, 5.5])

    def test_vertex_exactly_on_level_does_not_break_chains(self):
        tris = plane(lambda x, y: x, n=2)  # رأس‌ها دقیقاً روی ۰، ۵، ۱۰
        by = {}
        for c in surface.contours(tris, 5.0):
            by.setdefault(c["level"], []).append(c)
        self.assertEqual(len(by[5.0]), 1)
        self.assertTrue(all(abs(x - 5) < 1e-9 for x, _ in by[5.0][0]["coords"]))

    def test_guards(self):
        with self.assertRaises(surface.SurfaceError):
            surface.contours(plane(lambda x, y: x), 0)
        with self.assertRaises(surface.SurfaceError):
            surface.contours(plane(lambda x, y: x * 1000), 0.1)
        self.assertEqual(surface.contours([], 1.0), [])

    def test_auto_interval(self):
        self.assertEqual(surface.auto_interval(0, 10), 1)
        self.assertEqual(surface.auto_interval(100, 160), 5)
        self.assertEqual(surface.auto_interval(0, 0.5), 0.05)


class VolumeTests(SimpleTestCase):
    def test_flat_surface(self):
        v = surface.volume(plane(lambda x, y: 3.0), 1.0)
        self.assertAlmostEqual(v["cut"], 200.0)
        self.assertAlmostEqual(v["fill"], 0.0)

    def test_tilted_plane_balanced_around_mean(self):
        # z = x روی مربع ۱۰×۱۰ با ref=۵: نیمه‌ها برابرند و هر کدام ∫ = ۱۰×(۵×۲.۵) = ۱۲۵
        v = surface.volume(plane(lambda x, y: x, n=3), 5.0)
        self.assertAlmostEqual(v["cut"], 125.0, places=6)
        self.assertAlmostEqual(v["fill"], 125.0, places=6)
        self.assertAlmostEqual(v["net"], 0.0, places=6)

    def test_ref_not_aligned_with_grid(self):
        # z = x ؛ ref=۳ ⇒ cut = ۱۰×∫₃¹⁰(x−3) = ۱۰×۲۴٫۵، fill = ۱۰×∫₀³(3−x) = ۱۰×۴٫۵
        v = surface.volume(plane(lambda x, y: x, n=7), 3.0)
        self.assertAlmostEqual(v["cut"], 245.0, places=6)
        self.assertAlmostEqual(v["fill"], 45.0, places=6)

    def test_cone_volume_converges(self):
        # مخروط به ارتفاع ۵ و شعاع ۵ در مرکز مربع: حجم بالای صفر = π·r²·h/3
        tris = plane(lambda x, y: max(0.0, 5 - math.hypot(x - 5, y - 5)), n=60)
        v = surface.volume(tris, 0.0)
        self.assertAlmostEqual(v["cut"], math.pi * 25 * 5 / 3, delta=0.8)

    def test_two_positive_vertices_case(self):
        # z = 1 − y/2 روی مثلث (۰،۰)، (۴،۰)، (۰،۴): cut = ∫₀²(1−y/2)(4−y)dy = 10/3 ، fill = 2/3
        v = surface.volume([((0, 0, 1), (4, 0, 1), (0, 4, -1))], 0.0)
        self.assertAlmostEqual(v["cut"], 10 / 3, places=9)
        self.assertAlmostEqual(v["fill"], 2 / 3, places=9)

    def test_one_positive_vertex_case(self):
        # برعکس مورد بالا: z = y/2 − 1 ⇒ cut و fill جابه‌جا می‌شوند
        v = surface.volume([((0, 0, -1), (4, 0, -1), (0, 4, 1))], 0.0)
        self.assertAlmostEqual(v["cut"], 2 / 3, places=9)
        self.assertAlmostEqual(v["fill"], 10 / 3, places=9)


class FilterTests(SimpleTestCase):
    def test_long_edges_removed(self):
        tris = [((0, 0, 0), (1, 0, 0), (0, 1, 0)), ((0, 0, 0), (50, 0, 0), (0, 1, 0))]
        self.assertEqual(len(surface.filter_long_edges(tris, 10)), 1)
        self.assertEqual(len(surface.filter_long_edges(tris, None)), 2)
        self.assertEqual(surface.stats(tris[:1])["area"], 0.5)


class BetweenTests(SimpleTestCase):
    def test_flat_over_flat(self):
        v = surface.volume_between(plane(lambda x, y: 2.0, 4), plane(lambda x, y: 1.0, 4), cell=0.5)
        self.assertAlmostEqual(v["added"], 100.0, places=6)
        self.assertAlmostEqual(v["removed"], 0.0, places=6)
        self.assertAlmostEqual(v["area"], 100.0, places=6)

    def test_tilted_over_flat_balances(self):
        v = surface.volume_between(plane(lambda x, y: x, 5), plane(lambda x, y: 5.0, 3), cell=0.5)
        self.assertAlmostEqual(v["added"], 125.0, delta=0.5)
        self.assertAlmostEqual(v["removed"], 125.0, delta=0.5)
        self.assertAlmostEqual(v["net"], 0.0, delta=0.5)

    def test_only_overlap_counts(self):
        a = plane(lambda x, y: 3.0, 2)
        b = [tuple((x + 5, y, 1.0) for x, y, _ in t) for t in plane(lambda x, y: 0.0, 2)]  # [5,15]×[0,10]
        v = surface.volume_between(a, b, cell=0.5)
        self.assertAlmostEqual(v["area"], 50.0, places=6)
        self.assertAlmostEqual(v["added"], 100.0, places=6)

    def test_guards(self):
        far = [tuple((x + 100, y, 0.0) for x, y, _ in t) for t in plane(lambda x, y: 0.0)]
        with self.assertRaises(surface.SurfaceError):
            surface.volume_between(plane(lambda x, y: 0.0), far)
        with self.assertRaises(surface.SurfaceError):
            surface.volume_between(plane(lambda x, y: 0.0), plane(lambda x, y: 1.0), cell=0.001)
        with self.assertRaises(surface.SurfaceError):
            surface.volume_between([], plane(lambda x, y: 1.0))

    def test_agrees_with_exact_plane_volume_on_a_cone(self):
        cone = plane(lambda x, y: max(0.0, 5 - math.hypot(x - 5, y - 5)), n=50)
        v = surface.volume_between(cone, plane(lambda x, y: 0.0, 1), cell=0.1)
        self.assertAlmostEqual(v["added"], surface.volume(cone, 0.0)["cut"], delta=0.8)
