from django.urls import path

from . import views

app_name = "classroom"
urlpatterns = [
    path("", views.landing, name="landing"),
    path("teach/", views.teach, name="teach"),
    path("teach/<int:pk>/", views.detail, name="detail"),
    path("teach/<int:pk>/archive/<int:enrollment_id>/", views.archive_download, name="archive"),
    path("teach/<int:pk>/assignments/<int:aid>/", views.assignment_review, name="assignment_review"),
    path("teach/<int:pk>/assignments/<int:aid>/<int:eid>/", views.assignment_grade, name="assignment_grade"),
    path("join/", views.enter, name="enter"),
    path("join/<str:code>/", views.join, name="join"),
    path("join/<str:code>/assignments/<int:aid>/", views.assignment_page, name="assignment"),
    path("join/<str:code>/maps/<int:share_id>/copy/", views.copy_map, name="copy_map"),
]
