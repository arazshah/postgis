from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "billing"

urlpatterns = [
    path("plans/", views.plans, name="plans"),
    path("start/", views.start, name="start"),
    # نشانی‌های قدیمی بازار؛ نشانی تازه /plugins/ است (config/urls.py)
    path("market/", RedirectView.as_view(pattern_name="plugins", permanent=True), name="market"),
    path("market/trial/", views.start_trial, name="start_trial"),
    path("market/<slug:plugin_id>/", RedirectView.as_view(pattern_name="plugin_detail", permanent=True), name="market_detail"),
    path("start-addon/", views.start_addon, name="start_addon"),
    path("invoices/", views.invoices, name="invoices"),
    path("invoice/<str:number>/", views.invoice, name="invoice"),
    path("invoice/<str:number>/pay/", views.pay_gateway, name="pay_gateway"),
    path("invoice/<str:number>/receipt/", views.receipt, name="receipt"),
    path("invoice/<str:number>/receipt-file/", views.receipt_file, name="receipt_file"),
    path("invoice/<str:number>/cancel/", views.cancel, name="cancel"),
    path("callback/<str:number>/", views.callback, name="callback"),
]
