import secrets
from datetime import timedelta

from django.contrib.auth.hashers import make_password, check_password
from django.db import models
from django.utils import timezone

PASSWORD_RESET_TOKEN_EXPIRY_HOURS = 1


class FeUser(models.Model):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    password = models.CharField(max_length=255, default="!")
    is_active = models.BooleanField(default=True)
    is_confirmed = models.BooleanField(default=False)
    confirmation_token = models.CharField(max_length=64, blank=True, db_index=True)
    password_reset_token = models.CharField(max_length=64, blank=True, db_index=True)
    password_reset_expires = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["email"]
        db_table = "feusers"

    def __str__(self) -> str:
        return self.email

    def set_password(self, raw_password: str) -> None:
        self.password = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password(raw_password, self.password)

    def generate_confirmation_token(self) -> str:
        self.confirmation_token = secrets.token_urlsafe(32)
        return self.confirmation_token

    def generate_password_reset_token(self) -> str:
        self.password_reset_token = secrets.token_urlsafe(32)
        self.password_reset_expires = timezone.now() + timedelta(hours=PASSWORD_RESET_TOKEN_EXPIRY_HOURS)
        return self.password_reset_token

    def is_password_reset_token_valid(self) -> bool:
        return (
            bool(self.password_reset_token)
            and self.password_reset_expires is not None
            and timezone.now() < self.password_reset_expires
        )

    def clear_password_reset_token(self) -> None:
        self.password_reset_token = ""
        self.password_reset_expires = None
