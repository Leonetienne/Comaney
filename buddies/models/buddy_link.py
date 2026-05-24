from django.db import models
from django.utils import timezone


class BuddyLink(models.Model):
    """Confirmed mutual buddy relationship between two actual users.

    Convention: user_a.pk < user_b.pk. Always query with the helper below.
    """

    uid = models.BigAutoField(primary_key=True)
    user_a = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="buddy_links_a"
    )
    user_b = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="buddy_links_b"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_mod = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("user_a", "user_b")]
        ordering = ["created_at"]

    def other(self, feuser):
        return self.user_b if self.user_a_id == feuser.pk else self.user_a

    def __str__(self):
        return f"{self.user_a} <-> {self.user_b}"

    @staticmethod
    def for_user(feuser):
        from django.db.models import Q
        return BuddyLink.objects.filter(Q(user_a=feuser) | Q(user_b=feuser))

    @staticmethod
    def between(feuser_a, feuser_b):
        try:
            lo, hi = sorted([feuser_a, feuser_b], key=lambda u: u.pk)
            return BuddyLink.objects.get(user_a=lo, user_b=hi)
        except BuddyLink.DoesNotExist:
            return None
