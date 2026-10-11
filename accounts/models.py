from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("ایمیل الزامی است")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """کاربر با ورود از طریق ایمیل."""

    username = None
    email = models.EmailField("ایمیل", unique=True)
    full_name = models.CharField("نام و نام خانوادگی", max_length=150, blank=True)
    phone = models.CharField("موبایل", max_length=20, blank=True)
    organization = models.CharField("دانشگاه / سازمان", max_length=200, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"

    def __str__(self):
        return self.full_name or self.email

    @property
    def display_name(self):
        return self.full_name or self.email.split("@")[0]
