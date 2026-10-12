from django.urls import path

from . import views

app_name = "support"

urlpatterns = [
    path("", views.ticket_list, name="list"),
    path("new/", views.new, name="new"),
    path("t/<str:number>/", views.detail, name="detail"),
    path("t/<str:number>/close/", views.close, name="close"),
    path("file/<int:pk>/", views.attachment, name="attachment"),
]
