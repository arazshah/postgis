from django.urls import path

from . import views

app_name = "databases"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("new/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/password/", views.reset_password, name="reset_password"),
    path("<int:pk>/extensions/", views.add_extension, name="add_extension"),
    path("<int:pk>/renew/", views.renew, name="renew"),
    path("<int:pk>/delete/", views.delete, name="delete"),
    path("<int:pk>/backups/", views.backups, name="backups"),
    path("<int:pk>/backups/new/", views.backup_new, name="backup_new"),
    path("<int:pk>/backups/<int:job_id>/download/", views.backup_download, name="backup_download"),
    path("<int:pk>/backups/<int:job_id>/restore/", views.backup_restore, name="backup_restore"),
    path("<int:pk>/explore/", views.explore, name="explore"),
    path("<int:pk>/explore/sql/", views.explore_sql, name="explore_sql"),
    path("<int:pk>/explore/t/<str:schema>/<str:table>/", views.explore_table, name="explore_table"),
    path("<int:pk>/explore/t/<str:schema>/<str:table>/geojson/", views.explore_geojson, name="explore_geojson"),
    path("<int:pk>/explore/t/<str:schema>/<str:table>/csv/", views.explore_csv, name="explore_csv"),
]
