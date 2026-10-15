from django.urls import path, re_path

from . import manage, views

app_name = "restapi"
TABLE = r"(?P<path>[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?)"
urlpatterns = [
    path("rest/<slug:slug>/", views.index, name="index"),
    re_path(rf"^rest/(?P<slug>[-a-zA-Z0-9_]+)/{TABLE}/$", views.collection, name="collection"),
    re_path(rf"^rest/(?P<slug>[-a-zA-Z0-9_]+)/{TABLE}/(?P<pk>[^/]+)/$", views.item, name="item"),
    path("f/<slug:slug>/", views.form_page, name="form"),
    path("f/<slug:slug>/submit/", views.form_submit, name="form_submit"),
    path("f/<slug:slug>/manifest.webmanifest", views.form_manifest, name="form_manifest"),
    path("f/<slug:slug>/sw.js", views.form_sw, name="form_sw"),
    path("dashboard/<int:pk>/publish/rest/", manage.manage, name="manage"),
]
