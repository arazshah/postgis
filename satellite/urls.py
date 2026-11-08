from django.urls import path

from . import views

app_name = "satellite"
urlpatterns = [
    path("dashboard/<int:pk>/satellite/", views.index, name="index"),
    path("dashboard/<int:pk>/satellite/cards/", views.cards, name="cards"),
    path("dashboard/<int:pk>/satellite/layers/", views.layers, name="layers"),
    path("dashboard/<int:pk>/satellite/extent/", views.extent, name="extent"),
    path("dashboard/<int:pk>/satellite/quote/", views.quote, name="quote"),
    path("dashboard/<int:pk>/satellite/missions/", views.missions, name="missions"),
    path("dashboard/<int:pk>/satellite/search/", views.search, name="search"),
    path("dashboard/<int:pk>/satellite/order/", views.order, name="order"),
    path("dashboard/<int:pk>/satellite/thumb/<str:collection>/<str:item>.jpg", views.thumb, name="thumb"),
    path("dashboard/<int:pk>/satellite/<int:req>/delete/", views.delete, name="delete"),
    path("dashboard/<int:pk>/satellite/<int:req>/public/", views.toggle_public, name="toggle_public"),
    path("hooks/satellite/", views.hook, name="hook"),
]
