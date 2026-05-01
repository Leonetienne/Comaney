import secrets
from datetime import timedelta

from django.contrib.auth.hashers import make_password, check_password
from django.db import models
from django.utils import timezone

PASSWORD_RESET_TOKEN_EXPIRY_HOURS = 1


class FeUser(models.Model):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=128, blank=True)
    last_name = models.CharField(max_length=128, blank=True)
    password = models.CharField(max_length=255, default="!")
    is_active = models.BooleanField(default=True)
    is_confirmed = models.BooleanField(default=False)
    confirmation_token = models.CharField(max_length=64, blank=True, db_index=True)
    password_reset_token = models.CharField(max_length=64, blank=True, db_index=True)
    password_reset_expires = models.DateTimeField(null=True, blank=True)
    currency = models.CharField(max_length=10, blank=True, default="€")
    anthropic_api_key = models.CharField(max_length=255, blank=True)
    ai_custom_instructions = models.TextField(blank=True, max_length=1024)
    totp_secret = models.CharField(max_length=64, blank=True)
    totp_enabled = models.BooleanField(default=False)
    totp_recovery_hash = models.CharField(max_length=128, blank=True)
    ai_trial_budget_spent = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    ai_trial_budget_last_reset = models.DateTimeField(null=True, blank=True)
    month_start_day = models.SmallIntegerField(default=1)
    month_start_prev = models.BooleanField(default=False)
    pending_email = models.EmailField(blank=True)
    email_change_token = models.CharField(max_length=64, blank=True, db_index=True)
    api_key = models.CharField(max_length=64, blank=True, null=True, unique=True, db_index=True)
    email_notifications = models.BooleanField(default=True)
    unspent_allowance_action = models.CharField(
        max_length=20,
        default="do_nothing",
        choices=[
            ("do_nothing", "be dropped"),
            ("deposit_savings", "be deposited as savings"),
            ("carry_over", "carry over to next month"),
        ],
    )
    allowance_transition_month = models.CharField(max_length=10, blank=True)
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

    def generate_email_change_token(self, new_email: str) -> str:
        self.pending_email = new_email
        self.email_change_token = secrets.token_urlsafe(32)
        return self.email_change_token

    def generate_api_key(self) -> str:
        self.api_key = secrets.token_urlsafe(32)
        return self.api_key

    def revoke_api_key(self) -> None:
        self.api_key = None
