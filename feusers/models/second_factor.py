from django.db import models

from ..second_factor_registry import FactorType, register_factor_type


class SecondFactorAuth(models.Model):
    """Shared fields for every second-factor method. Concrete subclasses add
    their own method-specific fields and register themselves with
    feusers.second_factor_registry so login/removal/profile views never need
    to branch on a specific method."""

    feuser = models.ForeignKey("feusers.FeUser", on_delete=models.CASCADE, related_name="+")
    label = models.CharField(max_length=64, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["created_at"]


class TOTPFactor(SecondFactorAuth):
    secret = models.CharField(max_length=64)


class WebAuthnFactor(SecondFactorAuth):
    credential_id = models.CharField(max_length=255, unique=True)
    public_key = models.TextField()
    sign_count = models.PositiveIntegerField(default=0)
    transports = models.CharField(max_length=128, blank=True)


class EmailFactor(SecondFactorAuth):
    """A TOTP secret whose code is delivered to the feuser's own email address
    on request rather than generated locally by an authenticator app. See
    feusers/email_factor_service.py for the longer interval this uses (a
    plain 30s TOTP step would routinely expire before the email arrives) and
    the send-code throttling. Capped at one per feuser in email_factor_setup:
    unlike TOTP/WebAuthn, every instance would target the exact same address,
    so a second one adds nothing."""
    secret = models.CharField(max_length=64)


register_factor_type(FactorType(
    key="totp",
    model=TOTPFactor,
    display_name="Authenticator App",
    setup_url_name="totp_setup",
    challenge_template="feusers/twofa_challenge_totp.html",
    icon="dist/images/icons/qr-code.png",
))

register_factor_type(FactorType(
    key="webauthn",
    model=WebAuthnFactor,
    display_name="Security Key",
    setup_url_name="webauthn_setup",
    challenge_template="feusers/twofa_challenge_webauthn.html",
    icon="dist/images/icons/key.png",
))

register_factor_type(FactorType(
    key="email",
    model=EmailFactor,
    display_name="Email Code",
    setup_url_name="email_factor_setup",
    challenge_template="feusers/twofa_challenge_email.html",
    icon="dist/images/icons/mail.png",
))
