from django.db import models
from django.utils import timezone

from .base import OwnedModel


class Dashboard(OwnedModel):
    title = models.CharField(max_length=128)
    sorting = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    last_mod = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['sorting', 'uid']

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        if self.pk is not None:
            self.last_mod = timezone.now()
            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                kwargs['update_fields'] = list(update_fields) + ['last_mod']
        super().save(*args, **kwargs)


class DashboardCard(OwnedModel):
    dashboard = models.ForeignKey(
        Dashboard, on_delete=models.CASCADE, related_name='cards'
    )
    yaml_config = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    last_mod = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['created_at']

    def save(self, *args, **kwargs):
        if self.pk is not None:
            self.last_mod = timezone.now()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = list(update_fields) + ["last_mod"]
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"DashboardCard #{self.pk}"
