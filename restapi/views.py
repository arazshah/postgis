"""REST API عمومی جدول‌ها (/rest/<سرویس>/…) و فرم جمع‌آوری میدانی (/f/<شناسه>/)."""
import json

from django.core.cache import cache
from django.db.models import F
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from databases import team
from databases.models import UserDatabase
from publish import access
from publish.models import Service

from . import engine
from .models import ApiTable, FieldForm


def _json(data, status=200):
    resp = JsonResponse(data, status=status, safe=False, json_dumps_params={"ensure_ascii": False})
    resp["Access-Control-Allow-Origin"] = "*"
    resp["Access-Control-Allow-Headers"] = "Authorization, X-API-Key, Content-Type"
    resp["Access-Control-Allow-Methods"] = "GET, POST, PATCH, PUT, DELETE, OPTIONS"
    resp["Cache-Control"] = "no-store"
    return resp


def _err(status, msg):
    return _json({"code": status, "description": msg}, status)


def _split(path: str) -> tuple[str, str]:
    return tuple(path.split(".", 1)) if "." in path else ("public", path)


def _resolve(slug, path):
    svc = Service.objects.select_related("database__plan", "database__server").filter(slug=slug).first()
    if svc is None:
        raise access.Denied(404, "NotFound", "سرویس پیدا نشد.")
    db = svc.database
    access.check_database(db)
    schema, table = _split(path)
    t = ApiTable.objects.filter(service=svc, schema=schema, table=table).first()
    if t is None:
        raise access.Denied(404, "NotFound", "این جدول در REST API باز نشده است.")
    return db, t


def _authorize(request, db, t: ApiTable, op: str):
    """op: read | insert | update | delete. نوشتن فقط با کلید دارای اجازه نوشتن (نه نشست مرورگر)."""
    member = team.level(request.user, db) > 0
    key = access.key_for(request, db)
    if op == "read":
        if not (t.public_read or key or member):
            raise access.Denied(401, "Unauthorized", "کلید API بفرستید (هدر Authorization یا X-API-Key).")
    else:
        if not getattr(t, f"can_{op}"):
            raise access.Denied(405, "MethodNotAllowed", "این عملیات برای این جدول فعال نیست.")
        if key is None:
            raise access.Denied(401, "Unauthorized", "برای نوشتن، کلید API دارای «اجازه نوشتن» لازم است.")
        if not key.can_write:
            raise access.Denied(403, "Forbidden", "این کلید فقط اجازه خواندن دارد.")
        if db.status != UserDatabase.Status.ACTIVE:
            raise access.Denied(403, "ReadOnly", "پایگاه داده فقط‌خواندنی است (حجم پر شده یا غیرفعال).")
    if not member:
        access.count(db)


def _body(request):
    try:
        return json.loads(request.body or b"{}")
    except ValueError as exc:
        raise engine.RestError("بدنه درخواست JSON معتبر نیست.") from exc


@csrf_exempt
@require_http_methods(["GET", "OPTIONS"])
def index(request, slug):
    if request.method == "OPTIONS":
        return _json({})
    svc = Service.objects.select_related("database").filter(slug=slug).first()
    if svc is None:
        return _err(404, "سرویس پیدا نشد.")
    base = request.build_absolute_uri(f"/rest/{svc.slug}/")
    return _json({"tables": [{"name": t.path, "url": base + t.path + "/", "public_read": t.public_read,
                              "insert": t.can_insert, "update": t.can_update, "delete": t.can_delete}
                             for t in svc.api_tables.all()]})


@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def collection(request, slug, path):
    if request.method == "OPTIONS":
        return _json({})
    try:
        db, t = _resolve(slug, path)
        if request.method == "GET":
            _authorize(request, db, t, "read")
            params = request.GET.dict()
            for k in ("key",):
                params.pop(k, None)
            limit = params.pop("limit", engine.DEFAULT_LIMIT)
            offset = params.pop("offset", 0)
            order = params.pop("order", "")
            bbox = params.pop("bbox", "")
            box = [float(x) for x in bbox.split(",")] if bbox else None
            if box is not None and len(box) != 4:
                raise engine.RestError("bbox باید چهار عدد باشد.")
            return _json(engine.list_rows(db, t.schema, t.table, filters=params, bbox=box, order=order,
                                          limit=limit, offset=offset))
        _authorize(request, db, t, "insert")
        return _json(engine.insert(db, t.schema, t.table, _body(request)), 201)
    except access.Denied as exc:
        return _err(exc.status, exc.message)
    except engine.RestError as exc:
        return _err(exc.status, str(exc))
    except ValueError:
        return _err(400, "پارامتر عددی نامعتبر است.")


@csrf_exempt
@require_http_methods(["GET", "PATCH", "PUT", "DELETE", "OPTIONS"])
def item(request, slug, path, pk):
    if request.method == "OPTIONS":
        return _json({})
    try:
        db, t = _resolve(slug, path)
        if request.method == "GET":
            _authorize(request, db, t, "read")
            return _json(engine.get_row(db, t.schema, t.table, pk))
        if request.method == "DELETE":
            _authorize(request, db, t, "delete")
            engine.delete(db, t.schema, t.table, pk)
            return _json({}, 200)
        _authorize(request, db, t, "update")
        return _json(engine.update(db, t.schema, t.table, pk, _body(request)))
    except access.Denied as exc:
        return _err(exc.status, exc.message)
    except engine.RestError as exc:
        return _err(exc.status, str(exc))


# ---------------------------------------------------------------------- فرم میدانی
INPUT_TYPES = {"int2": "int", "int4": "int", "int8": "int", "float4": "float", "float8": "float", "numeric": "float",
               "bool": "bool", "date": "date", "timestamp": "datetime", "timestamptz": "datetime"}


def _form(request, slug) -> FieldForm:
    form = get_object_or_404(FieldForm.objects.select_related("api_table__service__database__plan"), slug=slug)
    db = form.api_table.service.database
    if db.status not in UserDatabase.LIVE_STATUSES:
        raise Http404
    return form


def _can_use(request, form) -> bool:
    if form.access == FieldForm.Access.PUBLIC:
        return True
    return team.level(request.user, form.api_table.service.database) > 0


def form_fields(form: FieldForm, meta: dict) -> list[dict]:
    byname = {c["name"]: c for c in meta["columns"]}
    out = []
    for name in form.fields:
        c = byname.get(name)
        if c is None or c is meta["geom"] or name == meta["pk"]:
            continue
        out.append({"name": name, "kind": INPUT_TYPES.get(c["base"], "text"),
                    "required": not c["nullable"] and not c["default"]})
    return out


def form_page(request, slug):
    form = _form(request, slug)
    db = form.api_table.service.database
    if not _can_use(request, form):
        from django.contrib.auth.views import redirect_to_login

        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        raise Http404
    try:
        meta = engine.describe(db, form.api_table.schema, form.api_table.table)
    except engine.RestError:
        raise Http404 from None
    from core.models import SiteSettings
    from iranmap import basemap

    cfg = {"submit": reverse("restapi:form_submit", args=[form.slug]), "fields": form_fields(form, meta),
           "hasGeom": bool(meta["geom"]), "open": form.is_open,
           "iranStyle": request.build_absolute_uri("/basemap/style.json") if basemap.available() else "",
           "basemap": SiteSettings.get().map_tile_url,
           "rtlPlugin": request.build_absolute_uri(static("vendor/rtl-text/mapbox-gl-rtl-text.js")),
           "queueKey": f"gp-form-{form.slug}"}
    return render(request, "restapi/form.html", {"form": form, "cfg": cfg})


def form_manifest(request, slug):
    form = _form(request, slug)
    data = {"name": form.title, "short_name": form.title[:24], "start_url": f"/f/{form.slug}/",
            "scope": f"/f/{form.slug}/", "display": "standalone", "dir": "rtl", "lang": "fa",
            "background_color": "#EEF2EC", "theme_color": "#0F5C59",
            "icons": [{"src": static("img/favicon.svg"), "sizes": "any", "type": "image/svg+xml"}]}
    return HttpResponse(json.dumps(data, ensure_ascii=False), content_type="application/manifest+json")


SW = """// سرویس‌ورکر فرم میدانی: صفحه و فایل‌هایش برای باز شدن بدون اینترنت نگه داشته می‌شوند
const CACHE = "gp-form-v1-%(slug)s";
const SHELL = ["/f/%(slug)s/", %(assets)s];
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  e.respondWith(fetch(req).then((res) => {
    if (res.ok && (SHELL.some((u) => req.url.endsWith(u)) || req.mode === "navigate")) {
      const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy));
    }
    return res;
  }).catch(() => caches.match(req, {ignoreSearch: true})));
});
"""


def form_sw(request, slug):
    form = _form(request, slug)
    assets = ", ".join(json.dumps(static(p)) for p in (
        "css/app.css", "vendor/maplibre/maplibre-gl.css", "vendor/maplibre/maplibre-gl.js", "js/field-form.js"))
    resp = HttpResponse(SW % {"slug": form.slug, "assets": assets}, content_type="application/javascript")
    resp["Service-Worker-Allowed"] = f"/f/{form.slug}/"
    resp["Cache-Control"] = "no-cache"
    return resp


@require_POST
def form_submit(request, slug):
    form = _form(request, slug)
    db = form.api_table.service.database
    if not _can_use(request, form):
        return _err(403, "برای این فرم باید با حساب عضو تیم وارد شوید.")
    if not form.is_open:
        return _err(403, "این فرم بسته شده است.")
    if db.status != UserDatabase.Status.ACTIVE:
        return _err(403, "پایگاه داده فقط‌خواندنی است؛ به مالک خبر دهید.")
    ip = (request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "").split(",")[0].strip()
    rk = f"gp-form-rate:{form.pk}:{ip}"
    if cache.get_or_set(rk, 0, 60) >= 30:
        return _err(429, "ارسال‌ها بیش از حد سریع است؛ یک دقیقه صبر کنید.")
    cache.incr(rk)
    try:
        body = json.loads(request.body or b"{}")
        meta = engine.describe(db, form.api_table.schema, form.api_table.table)
        allowed = {f["name"] for f in form_fields(form, meta)}
        values = {k: v for k, v in (body.get("properties") or {}).items() if k in allowed and v not in ("", None)}
        geom = body.get("geometry")
        if meta["geom"]:
            if not (isinstance(geom, dict) and geom.get("type") == "Point" and len(geom.get("coordinates") or []) >= 2):
                return _err(400, "موقعیت روی نقشه مشخص نشده است.")
            lon, lat = (float(x) for x in geom["coordinates"][:2])
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                return _err(400, "مختصات نامعتبر است.")
            values[meta["geom"]["name"]] = {"type": "Point", "coordinates": [lon, lat]}
        if team.level(request.user, db) == 0:
            access.count(db)
        row = engine.insert(db, form.api_table.schema, form.api_table.table, values)
    except access.Denied as exc:
        return _err(exc.status, exc.message)
    except engine.RestError as exc:
        return _err(exc.status, str(exc))
    except (ValueError, TypeError):
        return _err(400, "داده ارسالی نامعتبر است.")
    FieldForm.objects.filter(pk=form.pk).update(submissions=F("submissions") + 1)
    return _json({"ok": True, "id": row.get("id") if isinstance(row, dict) else None}, 201)
