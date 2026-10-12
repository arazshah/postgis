from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("plans/", views.plans, name="plans"),
    path("start/", views.start, name="start"),
    path("invoices/", views.invoices, name="invoices"),
    path("invoice/<str:number>/", views.invoice, name="invoice"),
    path("invoice/<str:number>/pay/", views.pay_gateway, name="pay_gateway"),
    path("invoice/<str:number>/receipt/", views.receipt, name="receipt"),
    path("invoice/<str:number>/receipt-file/", views.receipt_file, name="receipt_file"),
    path("invoice/<str:number>/cancel/", views.cancel, name="cancel"),
    path("callback/<str:number>/", views.callback, name="callback"),
]
