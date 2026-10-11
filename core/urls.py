from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("docs/", views.docs_index, name="docs"),
    path("docs/<slug:slug>/", views.docs_page, name="doc"),
    path("terms/", views.terms, name="terms"),
    path("healthz", views.healthz, name="healthz"),
]
