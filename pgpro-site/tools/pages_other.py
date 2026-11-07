from layout import ENDPOINT, FALLBACK, VERSION, icon, page


def crumbs(title):
    return f'<nav class="crumbs" aria-label="مسیر"><a href="/">خانه</a>{icon("chev", "s go")}<span>{title}</span></nav>'


def head_block(title, lead):
    return f'<div class="page-head"><div class="wrap">{crumbs(title)}<h1>{title}</h1><p>{lead}</p></div></div>'


def setup():
    toc = [("prep", "پیش‌نیازها"), ("write", "نوشتن کارت و روشن کردن"), ("login", "ورود و رمز تازه"), ("users", "کاربران و پایگاه‌ها"),
           ("qgis", "اتصال QGIS"), ("notfound", "اگر pgpro.local باز نشد"), ("clock", "ساعت دستگاه"), ("update", "به‌روزرسانی"), ("backup", "بکاپ"), ("reset", "فراموشی رمز"), ("support", "پشتیبانی فنی")]
    toc_html = '<b>در این صفحه</b>' + "".join(f'<a href="#{i}">{t}</a>' for i, t in toc)
    body = head_block("راهنمای راه‌اندازی", "از جعبه درآوردن تا اولین پایگاه PostGIS؛ قدم‌به‌قدم و بدون نیاز به دانش شبکه.") + f"""
<section><div class="wrap layout"><aside><nav class="toc" aria-label="فهرست">{toc_html}</nav></aside>
<div class="doc">
<h2 id="prep" class="first">پیش‌نیازها</h2>
<ul>
<li>دستگاه pgpro، آداپتور برق ۵ ولت و ۲ آمپر (باکیفیت؛ آداپتور ضعیف عامل اصلی ناپایداری است)</li>
<li>کارت microSD حداقل ۳۲ گیگابایت (ترجیحاً A1 یا A2)؛ اگر دستگاه را آماده خریده‌اید کارت داخل آن است</li>
<li>یک کابل شبکه به همان شبکه‌ای که رایانه‌ها در آن هستند</li>
<li>یک مرورگر مدرن روی رایانه یا گوشی در همان شبکه</li>
</ul>

<h2 id="write">نوشتن کارت و روشن کردن</h2>
<ol>
<li>فایل ایمیج <code class="ltr">pgpro-{VERSION}-nanopineo3.img.xz</code> را با <b>balenaEtcher</b> (یا Raspberry Pi Imager ← «Use custom») روی کارت بنویسید. فایل را از حالت فشرده خارج نکنید.</li>
<li>کارت را در دستگاه بگذارید، کابل شبکه و سپس برق را وصل کنید.</li>
<li><b>۳ تا ۵ دقیقه صبر کنید.</b> دستگاه در اولین روشن شدن رمزهای یکتای خودش و پایگاه داده را می‌سازد. خاموشش نکنید.</li>
<li>در مرورگر <code class="ltr">http://pgpro.local</code> را باز کنید. تا آماده شدن صفحه‌ی «در حال آماده‌سازی» دیده می‌شود و خودش تازه می‌شود.</li>
</ol>
<div class="callout info">{icon("info")}<span>اگر دستگاه را آماده خریده‌اید فقط مرحله‌ی ۲ تا ۴ لازم است.</span></div>

<h2 id="login">ورود و رمز تازه</h2>
<p>نام کاربری <code>admin</code> و رمز <code>pgpro</code>. بلافاصله رمز تازه خواسته می‌شود و تا عوض نکنید جای دیگری باز نمی‌شود. رمز را جای امنی نگه دارید.</p>

<h2 id="users">کاربران و پایگاه‌ها</h2>
<ol>
<li>از منوی حساب (دایره‌ی بالا) ← «کاربران» ← «کاربر تازه» برای هر همکار حساب بسازید. رمز موقت فقط یک بار نمایش داده می‌شود؛ به خود او بدهید.</li>
<li>در داشبورد «ساخت پایگاه داده» را بزنید؛ PostGIS و pgRouting آماده است.</li>
<li>با «ورود فایل» Shapefile، GeoPackage، GeoJSON، KML یا CSV را بارگذاری کنید. شماره‌ی موبایل هر کاربر برای اشتراک پایگاه با همکاران لازم است.</li>
</ol>

<h2 id="qgis">اتصال QGIS</h2>
<ol>
<li>در صفحه‌ی پایگاه، بخش «اتصال» نشانی، نام پایگاه و نام کاربری را نشان می‌دهد.</li>
<li>QGIS ← Layer ← Add Layer ← Add PostGIS Layers ← New.</li>
<li>Host را <code class="ltr">pgpro.local</code> و Port را <code>5432</code> بگذارید و نام پایگاه و کاربر را وارد کنید.</li>
</ol>
<pre>psql "host=pgpro.local port=5432 dbname=NAME user=USER"</pre>
<div class="callout">{icon("warn")}<span>پورت ۵۴۳۲ را هرگز روی اینترنت باز نکنید (Port Forward در روتر ممنوع). دستگاه برای شبکه‌ی داخلی ساخته شده است.</span></div>

<h2 id="notfound">اگر <span class="ltr">pgpro.local</span> باز نشد</h2>
<ul>
<li>ویندوز ۱۰ و ۱۱، مک، لینوکس و گوشی‌های جدید این نشانی را می‌شناسند. اگر شبکه‌ی سازمان کشف نام را بسته است، IP دستگاه را از صفحه‌ی مدیریت روتر (فهرست DHCP، نام <code>pgpro</code>) بخوانید و <code class="ltr">http://IP</code> را بزنید.</li>
<li>اگر روتر ندارید و کابل را مستقیم به لپ‌تاپ زده‌اید، یک دقیقه صبر کنید؛ دستگاه خودش آدرس محلی می‌گیرد و <code class="ltr">pgpro.local</code> کار می‌کند.</li>
<li>پس از اولین ورود، صفحه‌ی «دستگاه» (منوی حساب) نشانی‌های دستگاه را نشان می‌دهد.</li>
</ul>

<h2 id="clock">ساعت دستگاه</h2>
<p>دستگاه باتری ساعت ندارد و بدون اینترنت بعد از هر قطع برق ساعتش عقب می‌ماند. از صفحه‌ی «دستگاه» دکمه‌ی «هماهنگ‌سازی با این رایانه» را بزنید.</p>

<h2 id="update">به‌روزرسانی</h2>
<p>دستگاه نسخه‌ی تازه را از <b class="ltr">pgpro.ir/update</b> می‌گیرد.</p>
<ol>
<li><b>با اینترنت:</b> منوی حساب ← «دستگاه» ← «بررسی و به‌روزرسانی». داده‌ها و کاربران دست نمی‌خورند.</li>
<li>پیش از شروع از دیتابیس پنل بکاپ گرفته می‌شود؛ اگر نسخه‌ی تازه سالم بالا نیاید خودکار به نسخه‌ی قبل برمی‌گردد.</li>
<li>سرویس حدود یک دقیقه در دسترس نیست و صفحه خودش دوباره باز می‌شود.</li>
<li><b>بدون اینترنت:</b> بسته را از <a href="/download">صفحه‌ی نسخه‌ها</a> روی رایانه‌ی دیگری بگیرید و پشتیبان فنی روی دستگاه اعمال کند.</li>
</ol>

<h2 id="backup">بکاپ</h2>
<p>بکاپ شبانه‌ی پنل خودکار است. از «بکاپ و بازگردانی» در صفحه‌ی هر پایگاه بکاپ دستی بگیرید و بازگردانی کنید. بکاپ‌ها روی خود دستگاه می‌مانند؛ برای ایمنی در برابر خرابی کارت، فایل بکاپ را روی رایانه‌ی خودتان هم نگه دارید.</p>

<h2 id="reset">فراموشی رمز مدیر</h2>
<p>اگر مدیر دیگری دارید، از صفحه‌ی «کاربران» رمزتان را بازنشانی می‌کند. وگرنه پشتیبان فنی با SSH رمز را به <code>pgpro</code> برمی‌گرداند و ورود بعدی دوباره رمز تازه می‌خواهد. داده‌ها دست نمی‌خورد.</p>

<h2 id="support">پشتیبانی فنی</h2>
<p>پشتیبان فنی با کلید SSH اختصاصی (ورود با رمز خاموش است) به دستگاه وصل می‌شود. برای پشتیبانی از <a href="/order">فرم سفارش</a> یا <a href="https://postgis.ir/contact/?topic=pgpro">فرم تماس</a> استفاده کنید.</p>
</div></div></section>
"""
    return page("/setup", "راهنمای راه‌اندازی", "راه‌اندازی دستگاه pgpro قدم‌به‌قدم: نوشتن کارت، اتصال شبکه، ورود با pgpro.local، ساخت کاربر و پایگاه، اتصال QGIS، ساعت، به‌روزرسانی و فراموشی رمز.", body)


def specs():
    body = head_block("مشخصات فنی", "سخت‌افزار، نرم‌افزار و آنچه عمداً در این نسخه نیست؛ بدون عدد حدسی.") + f"""
<section><div class="wrap narrow doc">
<h2 class="first">سخت‌افزار</h2>
<div class="tbl-wrap"><table class="tbl"><tbody>
<tr><th>برد</th><td>FriendlyElec NanoPi NEO3، ۲ گیگابایت حافظه</td></tr>
<tr><th>پردازنده</th><td>Rockchip RK3328، چهار هسته‌ی Cortex-A53 (arm64)</td></tr>
<tr><th>حافظه</th><td>۲ گیگابایت DDR4</td></tr>
<tr><th>ذخیره‌سازی</th><td>کارت microSD (حداقل ۳۲ گیگابایت، A1/A2)؛ درگاه USB 3.0 برای SSD در فاز ۲</td></tr>
<tr><th>شبکه</th><td>یک درگاه Ethernet گیگابیت؛ بدون WiFi</td></tr>
<tr><th>تصویر</th><td>بدون HDMI؛ همه‌چیز از مرورگر</td></tr>
<tr><th>برق</th><td>۵ ولت، ۲ آمپر</td></tr>
<tr><th>ساعت</th><td>بدون باتری ساعت؛ هماهنگ‌سازی از پنل یا سرور زمان شبکه</td></tr>
<tr><th>قاب</th><td>جعبه‌ی سفید کوچک با چراغ‌های STAT و PWR</td></tr>
</tbody></table></div>
<p class="muted small mt-s">مشخصات برد از اطلاعات سازنده است و ممکن است در نسخه‌های سخت‌افزاری بعدی تغییر کند.</p>

<h2>نرم‌افزار</h2>
<div class="tbl-wrap"><table class="tbl"><tbody>
<tr><th>سیستم‌عامل</th><td>Armbian (Debian ۱۳)، بدون Docker؛ سرویس‌ها با systemd</td></tr>
<tr><th>پایگاه داده</th><td>PostgreSQL ۱۷ با PostGIS، pgRouting و pgvector</td></tr>
<tr><th>پنل</th><td>ژئوپایگاه (Django)، فارسی و راست‌به‌چپ، با nginx و gunicorn</td></tr>
<tr><th>نقشه‌ی پایه</th><td>ایران، Protomaps/OpenStreetMap تا بزرگنمایی ۱۴، آفلاین</td></tr>
<tr><th>یافتن دستگاه</th><td>mDNS (<span class="ltr">pgpro.local</span>)، نام DHCP، آدرس محلی برای اتصال مستقیم</td></tr>
<tr><th>اتصال کلاینت‌ها</th><td>PostgreSQL روی پورت ۵۴۳۲ فقط از شبکه‌های خصوصی</td></tr>
<tr><th>دسترسی SSH</th><td>فقط با کلید؛ ورود با رمز خاموش</td></tr>
<tr><th>به‌روزرسانی</th><td>از pgpro.ir با بکاپ پیش از شروع و برگشت خودکار</td></tr>
<tr><th>نسخه‌ی کنونی</th><td class="ltr">pgpro {VERSION} (آزمایشی)</td></tr>
</tbody></table></div>

<h2>ظرفیت</h2>
<p>دستگاه ۲ گیگابایت حافظه دارد؛ کارهای سنگین مثل درون‌ریزی کل OSM ایران، رستر بزرگ یا تحلیل‌های بسیار بزرگ ممکن است کند باشند یا سقف داشته باشند و پنل پیام فارسی روشن می‌دهد. حجم فایل ورودی به ۱۰۰ مگابایت محدود است. <b>تعداد کاربر هم‌زمان و سرعت‌ها هنوز در آزمون میدانی سنجیده نشده‌اند</b> و پس از سنجش اینجا ثبت می‌شوند.</p>

<h2>در این نسخه نیست</h2>
<ul>
<li>HTTPS محلی؛ بنابراین برداشت میدانی با GNSS و موقعیت مرورگر روی دستگاه خاموش است (در برنامه‌ی فاز ۲)</li>
<li>QGIS Server و سرویس WMS/WFS (فاز ۲)</li>
<li>داده‌ی آماده‌ی ایران، امکانات سازمانی و دستیار هوشمند</li>
<li>پرداخت و پیامک؛ ورود با نام کاربری و رمز است</li>
</ul>

<h2>نقشه‌ی راه</h2>
<div class="tbl-wrap"><table class="tbl"><thead><tr><th>فاز</th><th>محتوا</th><th>وضعیت</th></tr></thead><tbody>
<tr><th>۱</th><td>ایمیج آفلاین، چندکاربره، نقشه‌ی پایه، به‌روزرسانی</td><td><span class="tag teal">آماده‌ی آزمون</span></td></tr>
<tr><th>۲</th><td>SSD، بکاپ روی USB، HTTPS محلی، QGIS Server اختیاری، نام کوتاه <span class="ltr">pgpro</span> در ویندوز</td><td><span class="tag">برنامه‌ریزی</span></td></tr>
<tr><th>۳</th><td>مجوز و فعال‌سازی، برچسب سریال</td><td><span class="tag">برنامه‌ریزی</span></td></tr>
</tbody></table></div>
<div class="cta mt-m"><a class="btn warm" href="/order">درخواست پیش‌فاکتور</a><a class="btn alt" href="/setup">راهنمای راه‌اندازی</a></div>
</div></section>
"""
    return page("/specs", "مشخصات فنی", "مشخصات سخت‌افزار و نرم‌افزار دستگاه pgpro: NanoPi NEO3، PostgreSQL ۱۷، PostGIS، pgRouting، نقشه‌ی آفلاین ایران، محدودیت‌ها و نقشه‌ی راه.", body)


def download():
    body = head_block("نسخه‌ها و به‌روزرسانی", "کانال رسمی به‌روزرسانی دستگاه‌های pgpro و فهرست تغییرات.") + f"""
<section><div class="wrap narrow doc">
<div class="grid g2">
<div class="card"><h3><span class="ico">{icon("refresh")}</span>نسخه‌ی کنونی</h3><p><b class="ltr">pgpro {VERSION}</b> — آزمایشی. دستگاه‌ها از همین نشانی نسخه‌ی تازه را می‌گیرند.</p></div>
<div class="card"><h3><span class="ico">{icon("download")}</span>نشانی کانال</h3><p><code class="ltr">https://pgpro.ir/update/</code><br>فایل <code class="ltr">latest.json</code> نسخه و هش بسته را می‌گوید.</p></div>
</div>

<h2>به‌روزرسانی دستگاه</h2>
<ol>
<li>وارد پنل شوید ← منوی حساب ← «دستگاه» ← «بررسی و به‌روزرسانی».</li>
<li>دستگاه نسخه‌ی تازه را از <span class="ltr">pgpro.ir</span> می‌گیرد، از دیتابیس پنل بکاپ می‌گیرد، کنار نسخه‌ی قبل نصب می‌کند، مایگریشن می‌زند و سلامتش را می‌سنجد.</li>
<li>اگر سالم بالا نیاید خودکار به نسخه‌ی قبل برمی‌گردد.</li>
</ol>
<p>با SSH (پشتیبان فنی):</p>
<pre>sudo pgpro-update --check     # فقط بررسی
sudo pgpro-update --latest    # گرفتن و اعمال
sudo pgpro-update --rollback  # برگشت به نسخه‌ی قبل</pre>

<h2>دستگاه بدون اینترنت</h2>
<p>بسته‌ی به‌روزرسانی (حدود ۹۰ مگابایت) و فایل هش آن را از کانال بالا روی رایانه‌ی دیگری بگیرید و به دستگاه بفرستید:</p>
<pre>curl -fLO https://pgpro.ir/update/pgpro-update-latest.tar.xz
curl -fLO https://pgpro.ir/update/pgpro-update-latest.tar.xz.sha256
scp pgpro-update-latest.tar.xz support@pgpro.local:/tmp/
ssh support@pgpro.local sudo pgpro-update /tmp/pgpro-update-latest.tar.xz</pre>

<div class="callout">{icon("info")}<span>اگر فهرست بسته‌های پایتون عوض شده باشد، دستگاه باید آن‌ها را از اینترنت بگیرد؛ در غیر این صورت ایمیج کامل لازم است. ویدیوهای راهنما و نقشه‌ی پایه در بسته‌ی به‌روزرسانی نیستند.</span></div>

<h2>ایمیج کامل</h2>
<p>ایمیج کامل کارت (<code class="ltr">pgpro-{VERSION}-nanopineo3.img.xz</code> با فایل <code>.sha256</code>) در دوره‌ی پیش‌فروش برای مشتریان ارسال می‌شود. اگر دستگاه را خریده‌اید کارت آماده است.</p>
<p><a class="btn" href="/order?interest=trial">{icon("mail")}درخواست ایمیج آزمایشی</a></p>

<h2>فهرست تغییرات</h2>
<h3>pgpro {VERSION} — آزمایشی</h3>
<ul>
<li>ایمیج آفلاین روی NanoPi NEO3 با PostgreSQL، PostGIS، pgRouting و pgvector</li>
<li>ورود با نام کاربری و رمز، تغییر رمز اجباری، مدیریت کاربران</li>
<li>صفحه‌ی «دستگاه»: نشانی، وضعیت، هماهنگ‌سازی ساعت</li>
<li>نقشه‌ی پایه‌ی آفلاین ایران در همه‌ی بخش‌های نقشه</li>
<li>به‌روزرسانی با یک دکمه، بکاپ پیش از شروع و برگشت خودکار</li>
<li>رمزهای یکتا برای هر دستگاه و SSH فقط با کلید</li>
</ul>
</div></section>
"""
    return page("/download", "نسخه‌ها و به‌روزرسانی", "کانال به‌روزرسانی دستگاه pgpro، روش به‌روزرسانی با اینترنت و بدون اینترنت، ایمیج کامل و فهرست تغییرات.", body)


def order():
    def chip(name, value, label, checked=False):
        return f'<label class="chip"><input type="radio" name="{name}" value="{value}"{" checked" if checked else ""}><span>{label}</span></label>'

    interest = "".join([chip("interest", "quote", "پیش‌فاکتور", True), chip("interest", "preorder", "پیش‌فروش"), chip("interest", "trial", "نسخه‌ی آزمایشی"), chip("interest", "info", "فقط اطلاعات")])
    qty = "".join([chip("quantity", "1", "۱ دستگاه", True), chip("quantity", "2-5", "۲ تا ۵"), chip("quantity", "6-20", "۶ تا ۲۰"), chip("quantity", "20+", "بیشتر")])
    usage = "".join(chip("usage", u, u) for u in ["شهرداری و دولتی", "مشاور و پیمانکار", "معدن و صنعت", "دانشگاه", "سایر"])
    body = head_block("سفارش و پیش‌فاکتور", "نیازتان را بنویسید؛ همکاران ما با شما تماس می‌گیرند و پیش‌فاکتور می‌فرستند.") + f"""
<section><div class="wrap"><div class="split rev top">
<div class="panel"><form id="lead-form" class="form" data-endpoint="{ENDPOINT}" data-fallback="{FALLBACK}" novalidate>
<fieldset class="field"><legend>چه می‌خواهید؟</legend><div class="chips">{interest}</div></fieldset>
<fieldset class="field"><legend>تعداد دستگاه</legend><div class="chips">{qty}</div></fieldset>
<fieldset class="field"><legend>زمینه‌ی کار</legend><div class="chips">{usage}</div></fieldset>
<div class="row2">
<div class="field"><label for="f-name">نام و نام خانوادگی</label><input class="inp" id="f-name" name="name" autocomplete="name" required><span class="err" id="err-name"></span></div>
<div class="field"><label for="f-phone">شماره‌ی موبایل</label><input class="inp ltr" id="f-phone" name="phone" inputmode="tel" autocomplete="tel" placeholder="09123456789" required><span class="err" id="err-phone"></span></div>
</div>
<div class="row2">
<div class="field"><label for="f-org">سازمان یا شرکت</label><input class="inp" id="f-org" name="organization" autocomplete="organization"></div>
<div class="field"><label for="f-mail">ایمیل (اختیاری)</label><input class="inp" id="f-mail" name="email" type="email" autocomplete="email" dir="ltr"><span class="err" id="err-email"></span></div>
</div>
<div class="field"><label for="f-msg">توضیح (اختیاری)</label><textarea class="inp" id="f-msg" name="message" rows="4" maxlength="1500" placeholder="مثلاً چند شعبه‌ایم و داده‌ها باید در شبکه‌ی داخلی بماند"></textarea></div>
<div class="hp" aria-hidden="true"><label>وب‌سایت<input name="website" tabindex="-1" autocomplete="off"></label></div>
<div id="lead-note" class="note" role="status" aria-live="polite"></div>
<button class="btn warm lg" type="submit">{icon("mail")}ارسال درخواست</button>
<p class="muted small nomar">با ارسال، شماره‌تان فقط برای همین پیگیری استفاده می‌شود. درخواست در پنل ژئوپایگاه (postgis.ir) ثبت می‌شود.</p>
</form></div>
<div>
<h2>بعد از ارسال چه می‌شود؟</h2>
<ol class="steps one">
<li><h3>تماس</h3><p>در همان روز کاری با شما تماس می‌گیریم و نیازتان را می‌شنویم.</p></li>
<li><h3>پیش‌فاکتور</h3><p>بر اساس تعداد دستگاه، نصب و آموزش، پیش‌فاکتور رسمی می‌فرستیم.</p></li>
<li><h3>تحویل</h3><p>دستگاه آماده (یا ایمیج برای سخت‌افزار خودتان) تحویل می‌شود و راه‌اندازی را همراهی می‌کنیم.</p></li>
</ol>
<div class="callout info">{icon("info")}<span>نسخه‌ی آزمایشی برای ارزیابی پیش از خرید است و دستگاه نمونه در مرحله‌ی آزمون میدانی قرار دارد.</span></div>
<p class="muted">ترجیح می‌دهید از فرم عمومی تماس استفاده کنید؟ <a href="{FALLBACK}">فرم postgis.ir</a></p>
</div></div></div></section>
"""
    return page("/order", "سفارش و پیش‌فاکتور", "درخواست پیش‌فاکتور، پیش‌فروش یا نسخه‌ی آزمایشی دستگاه pgpro؛ فرم به پنل ژئوپایگاه می‌رود و همکاران ما تماس می‌گیرند.", body)


def not_found():
    body = f"""<section><div class="wrap narrow center">{icon("search", "l")}<h1>صفحه پیدا نشد</h1><p class="muted">نشانی را درست وارد نکرده‌اید یا صفحه جابه‌جا شده است.</p><p><a class="btn" href="/">بازگشت به خانه</a></p></div></section>"""
    return page("/404", "صفحه پیدا نشد", "این صفحه وجود ندارد.", body, banner=False).replace(
        '<link rel="canonical" href="https://pgpro.ir/404">', '<meta name="robots" content="noindex">')
