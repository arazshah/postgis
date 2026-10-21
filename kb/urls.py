from django.urls import path

from . import views

app_name = "kb"

urlpatterns = [
    path("kb/", views.index, name="index"),
    path("kb/search/", views.search, name="search"),
    path("kb/c/<slug:slug>/", views.category, name="category"),
    path("kb/api/articles.json", views.api_articles, name="api_articles"),
    path("kb/api/chunks.jsonl", views.api_chunks, name="api_chunks"),
    path("kb/<slug:slug>/", views.article, name="article"),
    path("kb/<slug:slug>/feedback/", views.feedback, name="feedback"),
    path("llms.txt", views.llms_txt, name="llms"),
    path("llms-full.txt", views.llms_full_txt, name="llms_full"),
]
