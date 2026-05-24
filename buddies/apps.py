from django.apps import AppConfig


class BuddiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "buddies"

    def ready(self):
        from django.db.models.signals import post_delete
        from buddies.models import BuddyLink, ProjectMember

        def _on_buddylink_delete(sender, instance, **kwargs):
            from buddies.services.partnership import check_auto_remove
            check_auto_remove(instance.user_a)
            check_auto_remove(instance.user_b)

        def _on_projectmember_delete(sender, instance, **kwargs):
            if instance.feuser_id:
                from buddies.services.partnership import check_auto_remove
                from feusers.models import FeUser
                try:
                    feuser = FeUser.objects.get(pk=instance.feuser_id)
                    check_auto_remove(feuser)
                except FeUser.DoesNotExist:
                    pass

        post_delete.connect(_on_buddylink_delete, sender=BuddyLink, weak=False)
        post_delete.connect(_on_projectmember_delete, sender=ProjectMember, weak=False)
