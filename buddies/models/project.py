from django.conf import settings
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone


# Who is allowed to manage a project's name, description and picture.
PERMISSION_LAXITY_ADMIN_ONLY = 0  # only the admin can manage the project (default)
PERMISSION_LAXITY_MEMBERS = 1  # any member may edit name, description and picture

PERMISSION_LAXITY_CHOICES = [
    (PERMISSION_LAXITY_ADMIN_ONLY, "Admin only"),
    (PERMISSION_LAXITY_MEMBERS, "Any member"),
]


class Project(models.Model):
    uid = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    admin_feuser = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="administered_groups"
    )
    group_picture = models.BooleanField(default=False)
    permission_laxity = models.PositiveSmallIntegerField(
        default=PERMISSION_LAXITY_ADMIN_ONLY,
        choices=PERMISSION_LAXITY_CHOICES,
    )
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

    def can_edit_details(self, feuser) -> bool:
        """True if feuser may edit the project's name, description and picture.

        The admin always may. Other members may only when the project's
        permission_laxity is set to PERMISSION_LAXITY_MEMBERS.
        """
        if self.admin_feuser_id == feuser.pk:
            return True
        if self.permission_laxity == PERMISSION_LAXITY_MEMBERS:
            return self.members.filter(feuser_id=feuser.pk).exists()
        return False

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
