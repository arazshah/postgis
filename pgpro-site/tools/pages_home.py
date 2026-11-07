import json

from layout import NAME, SITE, icon, page

FAQ = [
    ("pgpro دقیقاً چیست؟",
     "یک دستگاه کوچک است که ژئوپایگاه (همان پنل postgis.ir) و یک پایگاه داده‌ی PostgreSQL با PostGIS را داخل شبکه‌ی خود شما اجرا می‌کند. کارت را می‌نویسید، کابل می‌زنید و در مرورگر pgpro.local را باز می‌کنید؛ اینترنت لازم نیست."),
    ("آیا واقعاً بدون اینترنت کار می‌کند؟",
     "بله. همه‌ی نرم‌افزار و نقشه‌ی پایه‌ی ایران داخل خود دستگاه است و صفحه‌ها هیچ فایلی از اینترنت نمی‌خواهند. اینترنت فقط برای به‌روزرسانی از pgpro.ir لازم است و آن هم اختیاری است (بسته را می‌شود با فایل هم داد)."),
    ("با QGIS یا ArcGIS چطور وصل می‌شوم؟",
     "هر پایگاه داده‌ای که می‌سازید رشته‌ی اتصال PostgreSQL دارد (نشانی pgpro.local، پورت ۵۴۳۲). از هر رایانه‌ی همان شبکه می‌توانید با QGIS، ArcGIS Pro، GeoServer، ogr2ogr یا Python وصل شوید. پایگاه داده فقط از شبکه‌های خصوصی پذیرفته می‌شود."),
    ("چند نفر هم‌زمان می‌توانند کار کنند؟",
     "پنل چندکاربره است و مدیر برای هر همکار حساب می‌سازد. دستگاه ۲ گیگابایت حافظه دارد و برای تیم‌های کوچک و متوسط طراحی شده است. عدد دقیق هم‌زمانی را پس از آزمون میدانی اعلام می‌کنیم و عدد حدسی نمی‌نویسیم."),
    ("اگر برق قطع شود چه می‌شود؟",
     "PostgreSQL با تنظیمات ایمن (fsync روشن) و فایل‌سیستم دارای journal اجرا می‌شود و بعد از روشن شدن دوباره بالا می‌آید. بکاپ شبانه‌ی پنل هم هست. آزمون قطع ناگهانی روی دستگاه واقعی در فهرست آزمون‌های پیش از تحویل است."),
    ("ساعت دستگاه بعد از خاموشی عقب نمی‌ماند؟",
     "دستگاه باتری ساعت ندارد. با یک دکمه در صفحه‌ی «دستگاه» ساعت را از مرورگر مدیر هماهنگ می‌کنید؛ اگر در شبکه سرور زمان باشد خودکار هم می‌شود."),
    ("به‌روزرسانی چطور است؟",
     "با یک دکمه در پنل، از pgpro.ir. پیش از شروع از دیتابیس پنل بکاپ گرفته می‌شود و اگر نسخه‌ی تازه سالم بالا نیاید خودکار به نسخه‌ی قبل برمی‌گردد. داده‌ها و کاربران دست نمی‌خورند."),
    ("تفاوتش با postgis.ir چیست؟",
     "postgis.ir سرویس ابری و اشتراکی است؛ pgpro همان تجربه است ولی روی دستگاه خودتان و آفلاین. پرداخت، پیامک و دستیار هوشمند در pgpro نیست؛ ورود با نام کاربری و رمز است."),
    ("قیمت و زمان تحویل؟",
     "فعلاً پیش‌فروش و نسخه‌ی آزمایشی است. قیمت بر اساس تعداد دستگاه و نیاز شما با پیش‌فاکتور اعلام می‌شود؛ فرم سفارش را پر کنید."),
]


def ui_mock():
    return f"""<div class="win" aria-label="نمونه‌ی رابط پنل (تصویرسازی)">
<div class="win-bar"><i></i><i></i><i></i><span class="addr">http://pgpro.local/databases/zoning/</span></div>
<div class="ui">
<div class="ui-rail"><b>پایگاه zoning</b>
<span class="on">{icon("home")}نمای کلی</span><span>{icon("table")}جدول‌ها</span><span>{icon("search")}یافتن عارضه</span><span>{icon("code")}اجرای SQL</span><span>{icon("upload")}ورود فایل</span><span>{icon("layers")}نقشه‌ها</span><span>{icon("users")}تیم</span></div>
<div class="ui-main">
<h4>نمای کلی و اتصال</h4>
<div class="ui-kpis"><div><b>۱۲</b><small>جدول</small></div><div><b>۴٫۸</b><small>گیگ حجم</small></div><div><b>۳</b><small>کاربر</small></div></div>
<div class="ui-map"><svg viewBox="0 0 300 150" preserveAspectRatio="xMidYMid slice" aria-hidden="true"><path d="M20 120L70 60 130 90 190 30 270 70 250 130z" fill="#0F5C59" fill-opacity=".18" stroke="#0F5C59" stroke-width="2"/><path d="M60 140L110 100 170 120 230 90" fill="none" stroke="#E0A526" stroke-width="3"/><g fill="#E0A526" stroke="#12313A" stroke-width="1.5"><circle cx="70" cy="60" r="5"/><circle cx="130" cy="90" r="5"/><circle cx="190" cy="30" r="5"/><circle cx="270" cy="70" r="5"/></g></svg></div>
<div class="ui-code"><em>SELECT</em> name, <em>ST_Area</em>(geom::geography)/1e4 <em>AS</em> hectare<br><em>FROM</em> parcels <em>WHERE</em> ST_DWithin(geom, :pt, 500);</div>
</div></div></div>"""


def build():
    faq_html = "".join(f'<details><summary>{q}</summary><div><p>{a}</p></div></details>' for q, a in FAQ)
    faq_ld = [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in FAQ]
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "Organization", "@id": SITE + "/#org", "name": "ژئوپایگاه", "url": "https://postgis.ir/", "logo": SITE + "/assets/img/logo.svg"},
        {"@type": "WebSite", "@id": SITE + "/#site", "name": NAME, "alternateName": "pgpro.ir", "url": SITE + "/", "inLanguage": "fa-IR", "publisher": {"@id": SITE + "/#org"}},
        {"@type": "Product", "name": NAME, "alternateName": "PostGIS Pro", "image": SITE + "/assets/img/og.jpg", "brand": {"@type": "Brand", "name": "ژئوپایگاه"},
         "description": "دستگاه کوچک آفلاین با PostgreSQL، PostGIS و پنل ژئوپایگاه برای نگهداری داده‌ی مکانی سازمان در شبکه‌ی داخلی.",
         "offers": {"@type": "Offer", "availability": "https://schema.org/PreOrder", "url": SITE + "/order", "priceCurrency": "IRR", "seller": {"@id": SITE + "/#org"}}},
        {"@type": "FAQPage", "mainEntity": faq_ld}]}
    extra = '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>\n"
    body = f"""
<section class="hero"><div class="wrap"><div class="hero-grid">
<div>
<span class="tag">{icon("wifi-off", "s")}آفلاین · روی دستگاه خودتان</span>
<h1 class="mt-s">پایگاه داده‌ی مکانی سازمان شما، <span>داخل شبکه‌ی خودتان</span></h1>
<p class="lead">{NAME} همان ژئوپایگاه است که در یک جعبه‌ی کوچک جا گرفته: PostgreSQL با PostGIS، پنل فارسی و نقشه‌ی پایه‌ی ایران؛ بدون اینترنت، بدون اشتراک ابری، بدون اینکه داده از شبکه‌ی شما بیرون برود.</p>
<div class="cta"><a class="btn warm lg" href="/order">{icon("mail")}درخواست پیش‌فاکتور</a><a class="btn alt lg" href="#how">{icon("play")}چطور راه می‌افتد؟</a></div>
<ul class="facts"><li>{icon("check")}راه‌اندازی ۵ دقیقه‌ای</li><li>{icon("check")}اتصال QGIS و ArcGIS</li><li>{icon("check")}چند کاربر، بکاپ، به‌روزرسانی</li></ul>
</div>
<div class="stage">
<img src="/assets/img/device.svg" alt="دستگاه pgpro با کابل شبکه و برق" width="520" height="440">
<div class="url"><i></i>http://pgpro.local</div>
<div class="badge">{icon("wifi-off", "s")}بدون اینترنت</div>
</div>
</div></div></section>

<section class="alt-bg" id="why"><div class="wrap">
<div class="head"><span class="eyebrow">چرا آفلاین؟</span><h2>داده‌ای که نباید از شبکه بیرون برود</h2>
<p>برای شهرداری‌ها، مشاوران و پیمانکاران، معدن و صنعت، و هر جایی که قرارداد یا قانون می‌گوید داده‌ی مکانی در اتاق خودتان بماند.</p></div>
<div class="grid g4">
<div class="card"><h3><span class="ico">{icon("wifi-off")}</span>بدون اینترنت</h3><p>پنل، پایگاه داده و نقشه‌ی پایه روی خود دستگاه است. قطعی اینترنت کار شما را متوقف نمی‌کند.</p></div>
<div class="card"><h3><span class="ico">{icon("lock")}</span>داده در اتاق شما</h3><p>هیچ داده‌ای به ابر نمی‌رود. پایگاه داده فقط از شبکه‌های خصوصی پذیرفته می‌شود و رمز هر دستگاه یکتاست.</p></div>
<div class="card"><h3><span class="ico">{icon("users")}</span>کار تیمی</h3><p>مدیر برای هر همکار حساب می‌سازد و پایگاه را با نقش‌های بیننده، ویرایشگر و مالک به اشتراک می‌گذارد.</p></div>
<div class="card"><h3><span class="ico">{icon("bolt")}</span>بدون نصب سرور</h3><p>لینوکس، PostgreSQL، PostGIS و پنل از قبل نصب و تنظیم شده‌اند. نیازی به مدیر سیستم ندارید.</p></div>
</div></div></section>

<section id="how"><div class="wrap">
<div class="head"><span class="eyebrow">راه‌اندازی</span><h2>سه قدم تا پایگاه داده‌ی مکانی</h2><p>از جعبه درآوردن تا ساخت اولین پایگاه، حدود ۵ دقیقه (اولین روشن شدن ۳ تا ۵ دقیقه صبر می‌خواهد).</p></div>
<ol class="steps">
<li><h3><span class="ico">{icon("plug")}</span>وصل کنید</h3><p>کابل شبکه را به همان شبکه‌ی رایانه‌ها و آداپتور ۵ ولت را به برق بزنید.</p></li>
<li><h3><span class="ico">{icon("globe2")}</span>باز کنید</h3><p>در مرورگر <code class="ltr">http://pgpro.local</code> را بزنید. دستگاه رمزهای یکتای خودش را می‌سازد و صفحه‌ی ورود می‌آید.</p></li>
<li><h3><span class="ico">{icon("db")}</span>بسازید</h3><p>با <code>admin</code> وارد شوید، رمز تازه بگذارید، همکاران را اضافه و اولین پایگاه PostGIS را بسازید.</p></li>
</ol>
<p class="center mt-m"><a class="btn alt" href="/setup">راهنمای کامل راه‌اندازی{icon("chev", "s go")}</a></p>
</div></section>

<section class="alt-bg"><div class="wrap"><div class="split">
<div>
<span class="tag teal">{icon("play", "s")}دستگاه واقعی</span>
<h2 class="mt-s">این همان دستگاه است؛ لحظه‌ی اولین روشن شدن</h2>
<p class="muted">در این ویدیو دستگاه نمونه را می‌بینید که به برق و شبکه وصل شده و رایانه‌ی کناری صفحه‌ی «pgpro در حال آماده‌سازی است» را نشان می‌دهد. همین صفحه خودش تازه می‌شود و به ورود می‌رسد.</p>
<ul class="bullets">
<li>{icon("check")}جعبه‌ی کوچک، یک کابل شبکه و یک کابل برق</li>
<li>{icon("check")}چراغ STAT و PWR وضعیت را نشان می‌دهد</li>
<li>{icon("check")}نشانی pgpro.local بدون هیچ تنظیمی در شبکه دیده می‌شود</li>
</ul>
<div class="callout info">{icon("info")}<span>دستگاه نمونه در آزمون‌های میدانی است؛ برای همین نسخه‌ی آزمایشی و پیش‌فروش را باز کرده‌ایم، نه فروش عمومی.</span></div>
</div>
<figure class="photo vid"><video controls playsinline preload="none" poster="/assets/video/device-poster.jpg" aria-label="ویدیوی روشن شدن دستگاه pgpro"><source src="/assets/video/device.mp4" type="video/mp4"></video><figcaption>روشن شدن دستگاه نمونه و صفحه‌ی آماده‌سازی</figcaption></figure>
</div></div></section>

<section id="features"><div class="wrap"><div class="split rev">
{ui_mock()}
<div>
<span class="eyebrow tag teal">امکانات</span>
<h2 class="mt-s">همان پنل ژئوپایگاه، فارسی و راست‌به‌چپ</h2>
<ul class="bullets">
<li>{icon("check")}<span><b>جدول‌ها و SQL مکانی:</b> مرور داده، یافتن عارضه، کنسول SQL با PostGIS و pgRouting</span></li>
<li>{icon("check")}<span><b>ورود فایل:</b> Shapefile، GeoPackage، GeoJSON، KML و CSV با اصلاح هندسه‌ی نامعتبر</span></li>
<li>{icon("check")}<span><b>تحلیل بدون SQL:</b> بافر، نزدیک‌ترین، شمارش، شبکه‌ی شش‌ضلعی، هم‌پوشانی و ابزارهای آماده</span></li>
<li>{icon("check")}<span><b>نقشه و انتشار:</b> نقشه‌ی چندلایه، کاشی برداری، OGC API Features و REST API با کلید</span></li>
<li>{icon("check")}<span><b>مدیریت:</b> تیم و کاربران، بکاپ و بازگردانی، سلامت داده و مصرف منابع</span></li>
</ul>
<p class="muted small">تصویر بالا نمونه‌ی ساده‌شده‌ی رابط است.</p>
</div></div></div></section>

<section class="alt-bg" id="offline-map"><div class="wrap"><div class="split">
<div>
<span class="eyebrow tag">نقشه‌ی پایه</span>
<h2 class="mt-s">نقشه‌ی ایران، بدون اینترنت و با برچسب فارسی</h2>
<p class="muted">زیر لایه‌های شما، نقشه‌ی پایه‌ی ایران (داده‌ی OpenStreetMap به‌صورت Protomaps تا بزرگنمایی ۱۴) داخل خود دستگاه است. نمایش جدول، کنسول SQL، یافتن عارضه و نقشه‌های چندلایه همه از همین فایل می‌خوانند و هیچ درخواستی به بیرون نمی‌رود.</p>
<ul class="bullets"><li>{icon("check")}کاشی برداری MapLibre؛ تیز در هر اندازه‌ی صفحه</li><li>{icon("check")}نام جاها فارسی و راست‌به‌چپ درست نمایش داده می‌شود</li><li>{icon("check")}حتی با کابل اینترنت جدا کار می‌کند</li></ul>
</div>
<div class="card map-card"><img src="/assets/img/iran.svg" alt="نقشه‌ی ایران با گره‌های شبکه" width="360" height="326"></div>
</div></div></section>

<section id="qgis"><div class="wrap"><div class="split rev">
<div class="doc"><pre># QGIS ← Layer ← Add PostGIS Layers ← New
Host      pgpro.local
Port      5432
Database  zoning          # نام پایگاه شما
User      u_zoning_rw     # در صفحه‌ی پایگاه دیده می‌شود

# یا از خط فرمان
psql "host=pgpro.local port=5432 dbname=zoning user=u_zoning_rw sslmode=prefer"</pre></div>
<div>
<span class="eyebrow tag teal">اتصال</span>
<h2 class="mt-s">از هر رایانه‌ی شبکه به PostGIS وصل شوید</h2>
<p class="muted">رشته‌ی اتصال هر پایگاه در صفحه‌ی خودش آماده است. QGIS، ArcGIS Pro، GeoServer، ogr2ogr، GeoPandas و هر کلاینت PostgreSQL کار می‌کند.</p>
<p><a href="/setup#qgis">راهنمای اتصال QGIS{icon("chev", "s go")}</a></p>
</div></div></div></section>

<section class="dark"><div class="wrap">
<div class="head"><span class="eyebrow">امنیت و نگهداری</span><h2>برای دستگاهی که بی‌سر و صدا کار می‌کند</h2></div>
<div class="grid g3">
<div class="card"><h3><span class="ico">{icon("key")}</span>رمز یکتا برای هر دستگاه</h3><p>هیچ رمزی داخل ایمیج نیست. کلیدها و رمزها در اولین روشن شدن ساخته می‌شوند و رمز پیش‌فرض مدیر در اولین ورود اجباراً عوض می‌شود.</p></div>
<div class="card"><h3><span class="ico">{icon("shield")}</span>شبکه‌ی بسته</h3><p>پایگاه داده فقط از شبکه‌های خصوصی پذیرفته می‌شود. SSH فقط با کلید است و ورود با رمز خاموش.</p></div>
<div class="card"><h3><span class="ico">{icon("refresh")}</span>به‌روزرسانی با برگشت</h3><p>از pgpro.ir با یک دکمه. بکاپ پیش از شروع، و برگشت خودکار اگر نسخه‌ی تازه سالم بالا نیاید.</p></div>
<div class="card"><h3><span class="ico">{icon("clock")}</span>ساعت و بکاپ</h3><p>هماهنگ‌سازی ساعت با یک دکمه و بکاپ شبانه‌ی پنل با امکان بازگردانی از خود پنل.</p></div>
<div class="card"><h3><span class="ico">{icon("gauge")}</span>وضعیت دستگاه</h3><p>صفحه‌ی «دستگاه»: نشانی‌ها، IP، حافظه، فضا، دمای پردازنده و نسخه.</p></div>
<div class="card"><h3><span class="ico">{icon("life")}</span>پشتیبانی</h3><p>پشتیبان فنی با SSH و کلید اختصاصی می‌تواند رمز مدیر را بازنشانی یا لاگ‌ها را بررسی کند؛ داده‌ها دست نمی‌خورد.</p></div>
</div></div></section>

<section id="compare"><div class="wrap">
<div class="head"><span class="eyebrow">مقایسه</span><h2>دستگاه یا ابر؛ کدام برای شما؟</h2><p>هر دو یک محصول‌اند؛ تفاوت در جایی است که داده می‌ماند.</p></div>
<div class="tbl-wrap"><table class="tbl"><thead><tr><th></th><th>{NAME} (دستگاه)</th><th>postgis.ir (ابر)</th></tr></thead><tbody>
<tr><th>محل داده</th><td>داخل شبکه‌ی شما</td><td>سرور ابری postgis.ir</td></tr>
<tr><th>اینترنت</th><td class="yes">لازم نیست</td><td>لازم است</td></tr>
<tr><th>ورود</th><td>نام کاربری و رمز</td><td>شماره‌ی موبایل و کد پیامکی</td></tr>
<tr><th>کاربران</th><td>مدیر حساب می‌سازد</td><td>ثبت‌نام عمومی</td></tr>
<tr><th>نقشه‌ی پایه</th><td class="yes">آفلاین در خود دستگاه</td><td>آنلاین</td></tr>
<tr><th>WMS و WFS</th><td class="no">در نقشه‌ی راه</td><td class="yes">دارد</td></tr>
<tr><th>هزینه</th><td>خرید دستگاه (پیش‌فاکتور)</td><td>اشتراک ماهانه یا رایگان با سقف</td></tr>
<tr><th>مناسب برای</th><td>سازمان، پروژه‌ی محرمانه، محل بدون اینترنت پایدار</td><td>دانشجو، تازه‌کار، توسعه‌دهنده</td></tr>
</tbody></table></div>
<p class="muted small mt-s">در نسخه‌ی دستگاه پرداخت، پیامک، دستیار هوشمند و برداشت میدانی GNSS (نیازمند HTTPS) فعلاً نیست؛ جزئیات در <a href="/specs">مشخصات</a>.</p>
</div></section>

<section class="alt-bg" id="faq"><div class="wrap">
<div class="head"><span class="eyebrow">پرسش‌های متداول</span><h2>پیش از سفارش بدانید</h2></div>
<div class="faq">{faq_html}</div>
</div></section>

<section><div class="wrap"><div class="band">
<h2>برای سازمانتان یک pgpro بخواهید</h2>
<p>پیش‌فروش و نسخه‌ی آزمایشی باز است. تعداد دستگاه و زمینه‌ی کارتان را بنویسید تا پیش‌فاکتور بفرستیم.</p>
<div class="cta"><a class="btn warm lg" href="/order">درخواست پیش‌فاکتور</a><a class="btn ghost lg" href="/order?interest=trial">نسخه‌ی آزمایشی</a></div>
</div></div></section>
"""
    return page("/", f"{NAME} — PostGIS آفلاین روی دستگاه، داخل شبکه‌ی سازمان شما",
                "دستگاه کوچک آفلاین با PostgreSQL، PostGIS و پنل فارسی ژئوپایگاه و نقشه‌ی پایه‌ی ایران؛ بدون اینترنت، با اتصال QGIS و ArcGIS. پیش‌فروش و نسخه‌ی آزمایشی.",
                body, extra)
