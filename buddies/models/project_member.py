from django.db import models
from django.utils import timezone


class ProjectMember(models.Model):
    uid = models.BigAutoField(primary_key=True)
    group = models.ForeignKey("buddies.Project", on_delete=models.CASCADE, related_name="members")
    feuser = models.ForeignKey(
        "feusers.FeUser", null=True, blank=True, on_delete=models.CASCADE,
        related_name="group_memberships"
    )
    dummy = models.ForeignKey(
        "buddies.DummyUser", null=True, blank=True, on_delete=models.CASCADE,
        related_name="group_memberships"
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    sorting = models.IntegerField(default=1)
    last_mod = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["joined_at"]

    def __str__(self):
        return f"{self.feuser or self.dummy} in {self.group}"


BuddyGroupMember = ProjectMember
