from django.db import models
from django.utils import timezone


class SankeyGraph(models.Model):
    """A feuser's single, persisted Sankey Studio node/edge graph
    definition. One per feuser, not a collection of named diagrams: it's
    meant to be extended over time (new tags/categories/projects placed in
    as they're created), not rebuilt from scratch.

    config_json shape:
        {
          "nodes": {
            "tag:3":          {"x": 100, "y": 200, "priority": 5, "disabled": false, "color": "#33aa66"},
            "connector:ab12": {"x": 300, "y": 400, "priority": 0, "label": "Connector", "color": "#5b8fb0"}
          },
          "edges": [{"source": "category:1", "target": "tag:3"}, ...]
        }

    Node keys: "tag:<pk>" / "category:<pk>" / "project:<pk>" for real
    catalog entities, "connector:<token>" for an explicitly user-placed
    passthrough/wiring node. See budget/sankey_service.py for the routing
    algorithm that consumes this structure.
    """
    feuser = models.OneToOneField(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="sankey_graph"
    )
    config_json = models.TextField(default="{}")
    created_at = models.DateTimeField(auto_now_add=True)
    last_mod = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"SankeyGraph(feuser={self.feuser_id})"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            self.last_mod = timezone.now()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = list(update_fields) + ["last_mod"]
        super().save(*args, **kwargs)
