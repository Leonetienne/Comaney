from django.db import models
from django.utils import timezone

from .base import OwnedModel


class Category(OwnedModel):
    title = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    last_mod = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title

    def update_lastmod(self) -> None:
        self.last_mod = timezone.now()
        self.save(update_fields=["last_mod"])
