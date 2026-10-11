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
]
