from django.conf import settings
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone


class Project(models.Model):
    uid = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    admin_feuser = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="administered_groups"
    )
    group_picture = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    archived = models.BooleanField(default=False)
    last_mod = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def description_inline(self) -> str:
        import re
        return re.sub(r'\s+', ' ', self.description).strip()

    def update_lastmod(self):
        self.last_mod = timezone.now()
        self.save(update_fields=["last_mod"])

    @property
    def is_solo(self) -> bool:
        """True if this project has exactly one feuser member and no dummy members."""
        members = list(self.members.all())
        feuser_count = sum(1 for m in members if m.feuser_id)
        dummy_count = sum(1 for m in members if m.dummy_id)
        return feuser_count == 1 and dummy_count == 0


# Keep BuddyGroup as an alias so existing code that imports it still works
# during the transition period. Remove after all references are updated.
BuddyGroup = Project


@receiver(pre_delete, sender=Project)
def _cleanup_group_picture(sender, instance, **kwargs):
    if instance.group_picture:
        (settings.MEDIA_ROOT / "bgpics" / f"{instance.pk}.webp").unlink(missing_ok=True)
