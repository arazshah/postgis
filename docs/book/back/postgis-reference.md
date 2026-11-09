---
title: پیوست ب ـ مرجع توابع پرکاربرد PostGIS
---

حدود هفتاد تابعی که کار روزمره‌ی بیشتر کارشناسان را پوشش می‌دهد، به ترتیب کاربرد. ستون آخر فصلی است که تابع در آن آموزش داده شده است. برای فهرست کامل،
مستندات رسمی PostGIS را ببینید.

## ساختن هندسه

| تابع | کار | فصل |
|---|---|---|
| `ST_Point(x, y, srid)` | نقطه با SRID (PostGIS ۳٫۲+) | ۱۵ |
| `ST_MakePoint(x, y [, z])` | نقطه بدون SRID | ۱۵ |
| `ST_SetSRID(g, srid)` | برچسب SRID (بدون تبدیل) | ۳ |
| `ST_GeomFromText(wkt, srid)` | از WKT | ۱۵ |
| `ST_GeomFromGeoJSON(json)` | از GeoJSON | ۱۵ |
| `ST_MakeLine(a, b)` / `ST_MakeLine(g ORDER BY t)` | خط از نقطه‌ها؛ تجمیعی برای مسیر | ۱۵ |
| `ST_MakePolygon(ring)` | چندضلعی از حلقه‌ی بسته | ۱۵ |
| `ST_MakeEnvelope(xmin, ymin, xmax, ymax, srid)` | مستطیل | ۱۵ |
| `ST_Collect(g)` | چندبخشی (تجمیعی) | ۱۲ و ۱۸ |

## خروجی و قالب

| تابع | کار | فصل |
|---|---|---|
| `ST_AsText(g)` / `ST_AsEWKT(g)` | WKT / با SRID | ۱۵ |
| `ST_AsGeoJSON(g, digits)` | GeoJSON؛ با سطر کامل، Feature | ۱۵ |
| `ST_AsKML`، `ST_AsGML`، `ST_AsSVG` | قالب‌های دیگر | ۱۵ |
| `ST_AsMVT`، `ST_AsMVTGeom` | کاشی برداری | ۴۵ |
| `ST_GeoHash(g, n)` | رشته‌ی geohash | ۱۵ |

## خواندن اجزا

| تابع | کار | فصل |
|---|---|---|
| `GeometryType(g)`، `ST_GeometryType(g)` | نوع هندسه | ۱۵ |
| `ST_SRID(g)`، `Find_SRID(schema, table, col)` | SRID | ۳ |
| `ST_X`، `ST_Y`، `ST_Z` | مختصات نقطه | ۱۵ |
| `ST_NPoints`، `ST_NumGeometries`، `ST_GeometryN` | رأس‌ها و اجزا | ۱۵ |
| `ST_StartPoint`، `ST_EndPoint`، `ST_PointN` | نقطه‌های خط | ۱۵ و ۲۴ |
| `ST_ExteriorRing`، `ST_InteriorRingN` | حلقه‌ها | ۱۵ و ۲۲ |
| `ST_Dump(g)`، `ST_DumpPoints(g)` | شکافتن به سطرها | ۱۵ |
| `ST_Envelope`، `ST_Extent` (تجمیعی) | محدوده | ۱۲ و ۱۵ |
| `ST_Centroid`، `ST_PointOnSurface` | مرکز ثقل / نقطه‌ی تضمینی داخل | ۱۵ |

## تبدیل مختصات

| تابع | کار | فصل |
|---|---|---|
| `ST_Transform(g, srid)` | تبدیل واقعی مختصات | ۳ |
| `ST_Transform(g, 'متن PROJ')` | تبدیل به تصویر سفارشی | ۱۶ |
| `g::geography` | محاسبه روی بیضوی (متر) | ۳ و ۱۶ |
| `ST_FlipCoordinates(g)` | جابه‌جایی x و y | ۱۸ |

## اندازه‌گیری

| تابع | کار | فصل |
|---|---|---|
| `ST_Distance(a, b)` | کوتاه‌ترین فاصله | ۱۶ |
| `ST_DistanceSphere(a, b)` | فاصله‌ی کروی سریع (متر) | ۱۶ |
| `ST_Length(g)`، `ST_3DLength(g)` | طول | ۱۶ و ۲۲ |
| `ST_Area(g)`، `ST_Perimeter(g)` | مساحت و محیط | ۱۶ |
| `ST_Azimuth(a, b)`، `ST_Project(p, d, az)` | جهت / نقطه در جهت | ۱۶ |
| `ST_ShortestLine(a, b)`، `ST_ClosestPoint(a, b)` | خط و نقطه‌ی نزدیک‌ترین | ۱۶ و ۱۹ |
| `ST_MaxDistance`، `ST_HausdorffDistance` | دورترین فاصله / شباهت شکل | ۱۶ |

## روابط مکانی (درست/نادرست)

| تابع | درست وقتی | فصل |
|---|---|---|
| `ST_Intersects(a, b)` | نقطه‌ی مشترک دارند | ۱۷ |
| `ST_Contains(a, b)`، `ST_Within(a, b)` | کاملاً داخل (مرز حساب نمی‌شود) | ۱۷ |
| `ST_Covers(a, b)`، `ST_CoveredBy(a, b)` | کاملاً داخل (با مرز) | ۱۷ |
| `ST_Touches`، `ST_Crosses`، `ST_Overlaps` | تماس، گذر، همپوشانی جزئی | ۱۷ |
| `ST_Equals(a, b)` | از نظر مکانی یکسان | ۱۷ |
| `ST_Disjoint(a, b)` | جدا | ۱۷ |
| `ST_DWithin(a, b, d)` | تا فاصله‌ی d (با شاخص) | ۸، ۱۷ و ۱۹ |
| `ST_Relate(a, b [, pattern])` | ماتریس DE-9IM / الگو | ۱۷ |
| `a && b` | برخورد مستطیل‌ها (عملگر شاخص) | ۲۰ |
| `a <-> b` | فاصله برای نزدیک‌ترین همسایه (با شاخص) | ۱۹ |

## پردازش هندسه

| تابع | کار | فصل |
|---|---|---|
| `ST_Buffer(g, d [, opts])` | حریم | ۱۸ |
| `ST_Union(g)` (تجمیعی) / `ST_Union(a, b)` | ادغام | ۱۸ |
| `ST_Intersection`، `ST_Difference`، `ST_SymDifference` | همپوشانی | ۱۸ |
| `ST_Simplify`، `ST_SimplifyPreserveTopology`، `ST_SimplifyVW` | ساده‌سازی | ۱۸ |
| `ST_SnapToGrid`، `ST_ReducePrecision`، `ST_Snap` | گرد کردن / چسباندن | ۱۸ |
| `ST_ConvexHull`، `ST_ConcaveHull(g, ratio)` | پوسته | ۱۸ |
| `ST_VoronoiPolygons`، `ST_DelaunayTriangles` | ورونوی / دلونی | ۱۸ |
| `ST_Subdivide(g, n)` | خرد کردن برای کارایی | ۱۸ و ۲۰ |
| `ST_Split(g, blade)` | بریدن با خط | ۱۸ |
| `ST_LineInterpolatePoint`، `ST_LineLocatePoint`، `ST_LineSubstring` | ارجاع خطی | ۱۸ و ۳۸ |
| `ST_LineMerge(g)` | پیوستن خط‌ها | ۲۴ |
| `ST_GeneratePoints(poly, n)` | نقطه‌ی تصادفی | ۱۸ |
| `ST_Multi`، `ST_CollectionExtract(g, type)`، `ST_Force2D` | تبدیل نوع | ۱۸ و ۲۲ |

## اعتبار و توپولوژی

| تابع | کار | فصل |
|---|---|---|
| `ST_IsValid`، `ST_IsValidReason`، `ST_IsValidDetail` | بررسی اعتبار | ۷ و ۲۲ |
| `ST_MakeValid(g [, 'method=structure'])` | اصلاح | ۲۲ |
| `ST_IsEmpty(g)` | هندسه‌ی خالی | ۱۸ |
| `topology.CreateTopology`، `toTopoGeom` | توپولوژی ذخیره‌شده | ۲۲ |

## شبکه‌ی منظم و خوشه‌بندی

| تابع | کار | فصل |
|---|---|---|
| `ST_HexagonGrid(size, bounds)`، `ST_SquareGrid` | شبکه‌ی شش‌ضلعی و مربعی | ۲۱ |
| `ST_ClusterDBSCAN(g, eps, minpoints) OVER ()` | خوشه‌های چگال | ۲۱ |
| `ST_ClusterKMeans(g, k) OVER ()` | k گروه | ۲۱ |
| `ST_ClusterWithin(g, d)` | زنجیره‌ی فاصله | ۲۱ |

## رستر

| تابع | کار | فصل |
|---|---|---|
| `ST_MetaData`، `ST_SummaryStats`، `ST_ValueCount` | فراداده و آمار | ۲۳ |
| `ST_Value(rast, point)` | مقدار در نقطه | ۲۳ |
| `ST_Clip(rast, geom)` | برش با چندضلعی | ۲۳ |
| `ST_MapAlgebra` | جبر نقشه | ۲۳ و ۳۵ |
| `ST_Reclass` | طبقه‌بندی دوباره | ۲۳ |
| `ST_Slope`، `ST_Aspect`، `ST_HillShade` | تحلیل ارتفاع | ۲۳ و ۳۸ |
| `ST_Contour` | منحنی میزان | ۳۸ |
| `ST_DumpAsPolygons`، `ST_AsRaster` | رستر ↔ برداری | ۲۳ |
| `ST_AsPNG`، `ST_AsGDALRaster` | خروجی | ۲۳ |

## سه‌بعدی (SFCGAL)

| تابع | کار | فصل |
|---|---|---|
| `ST_3DDistance`، `ST_3DLength` | فاصله و طول سه‌بعدی | ۲۲ |
| `ST_Extrude(g, dx, dy, dz)` | حجم از ردپا | ۲۲ |
| `ST_Volume(ST_MakeSolid(g))`، `ST_3DArea` | حجم و سطح | ۲۲ |

## pgRouting

| تابع | کار | فصل |
|---|---|---|
| `pgr_dijkstra(edges_sql, from, to)` | کوتاه‌ترین مسیر | ۲۴ |
| `pgr_aStar`، `pgr_bdDijkstra`، `pgr_KSP` | مسیر با حدس، دوطرفه، k مسیر | ۲۴ |
| `pgr_drivingDistance(edges_sql, from, cost)` | حوزه‌ی دسترسی | ۲۴ |
| `pgr_dijkstraCost`، `pgr_dijkstraCostMatrix` | ماتریس هزینه | ۲۴ |
| `pgr_TSP` | فروشنده‌ی دوره‌گرد | ۲۴ |
| `pgr_extractVertices`، `pgr_connectedComponents` | توپولوژی و بخش‌های شبکه | ۲۴ |

## توابع SQL عمومی که در کار مکانی زیاد لازم‌اند

| تابع | کار | فصل |
|---|---|---|
| `coalesce(a, b)`، `nullif(a, b)` | جایگزین NULL / جلوگیری از تقسیم بر صفر | ۱۰ و ۱۳ |
| `round(x::numeric, n)` | گرد کردن (توجه به `::numeric`) | ۱۵ |
| `percentile_cont(p) WITHIN GROUP (ORDER BY x)` | میانه و صدک | ۱۲ |
| `count(*) FILTER (WHERE …)` | شمارش شرطی | ۱۲ |
| `rank()`، `row_number()`، `lag()`، `lead()` با `OVER` | توابع پنجره‌ای | ۱۲ و ۳۷ |
| `DISTINCT ON (…)` | اولین سطر هر گروه | ۲۴ و ۳۶ |
| `generate_series(a, b [, step])` | دنباله‌ی عدد یا تاریخ | ۱۸ و ۲۰ |
| `regr_slope`، `regr_r2`، `corr` | رگرسیون و همبستگی | ۱۲ و ۳۷ |
| `translate(s, from, to)` | یکدست کردن رقم فارسی و «ی/ک» | ۱۱ |
| `similarity(a, b)`، `a % b` (pg_trgm) | تشابه متن | ۱۱ |
