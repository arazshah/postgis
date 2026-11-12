from django.urls import path

from kernel import routes

from . import views

app_name = "databases"

# نماهای خود میزبانی (ساخت، نمای کلی، رمز، افزونه، تمدید، حذف). بخش‌های داده (جدول‌ها، SQL، یافتن، ورود، سلامت،
# بکاپ، مصرف، تیم) پلاگین جدا هستند و مسیرشان را با kernel.routes در همین فضای‌نام ثبت می‌کنند؛ نام و نشانی‌ها ثابت مانده است.
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("new/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/password/", views.reset_password, name="reset_password"),
    path("<int:pk>/extensions/", views.add_extension, name="add_extension"),
    path("<int:pk>/renew/", views.renew, name="renew"),
    path("<int:pk>/delete/", views.delete, name="delete"),
]
urlpatterns += routes.patterns("databases")
