from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("help/", views.help_index, name="help"),
    path("help/<slug:slug>/", views.help_page, name="help_page"),
    path("docs/", views.docs_index, name="docs"),
    path("docs/<slug:slug>/", views.docs_page, name="doc"),
    path("terms/", views.terms, name="terms"),
    path("healthz", views.healthz, name="healthz"),
    path("robots.txt", views.robots_txt, name="robots"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap"),
]
