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
