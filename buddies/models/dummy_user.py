from django.conf import settings
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone


class DummyUser(models.Model):
    uid = models.BigAutoField(primary_key=True)
    owning_feuser = models.ForeignKey(
        "feusers.FeUser", null=True, blank=True, on_delete=models.CASCADE, related_name="dummy_buddies"
    )
    owning_group = models.ForeignKey(
        "buddies.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="dummy_members"
    )
    display_name = models.CharField(max_length=128)
    is_archive = models.BooleanField(default=False)
    profile_picture = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_mod = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["display_name"]

    def __str__(self):
        return self.display_name

    @property
    def initials(self) -> str:
        parts = self.display_name.split()
        if len(parts) >= 2:
            return (parts[0][:1] + parts[-1][:1]).upper()
        return self.display_name[:2].upper()

    def update_lastmod(self) -> None:
        self.last_mod = timezone.now()
        self.save(update_fields=["last_mod"])

    @property
    def ppic_url(self) -> str:
        return f"/media/offline-buddy-ppic/{self.pk}.jpg"


@receiver(pre_delete, sender=DummyUser)
def _cleanup_dummy_picture(sender, instance, **kwargs):
    if instance.profile_picture:
        (settings.MEDIA_ROOT / "offline-buddy-ppic" / f"{instance.pk}.jpg").unlink(missing_ok=True)
