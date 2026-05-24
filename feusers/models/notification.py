from django.db import models

NOTIFICATION_TYPE_CHOICES = [
    ("expense_reminders",            "Expense due date reminders"),
    ("expense_settled",              "Expense marked as paid"),
    ("expense_participation",        "Shared expense participation"),
    ("expense_assignments",          "Expense assignment"),
    ("participant_decisions",        "Participant decisions"),
    ("settlements",                  "Settlements"),
    ("group_activity",               "Project membership"),
    ("own_partnership_changes",      "Partnership changes (you)"),
    ("someones_partnership_changes", "Partnership changes (others)"),
]

# Maps notification type to the FeUser boolean field that controls it
NOTIFICATION_TYPE_PREF = {
    "expense_reminders":            "notify_expense_reminders",
    "expense_settled":              "notify_expense_settled",
    "expense_participation":        "notify_expense_participation",
    "expense_assignments":          "notify_expense_assignments",
    "participant_decisions":        "notify_participant_decisions",
    "settlements":                  "notify_settlements",
    "group_activity":               "notify_group_activity",
    "own_partnership_changes":      "notify_own_partnership_changes",
    "someones_partnership_changes": "notify_someones_partnership_changes",
}


class Notification(models.Model):
    owning_feuser = models.ForeignKey(
        "feusers.FeUser", on_delete=models.CASCADE, related_name="notifications",
    )
    type = models.CharField(max_length=40, choices=NOTIFICATION_TYPE_CHOICES)
    subject = models.CharField(max_length=255)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False, db_index=True)
    related_project = models.ForeignKey(
        "buddies.Project", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    related_feuser = models.ForeignKey(
        "feusers.FeUser", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    related_expense = models.ForeignKey(
        "budget.Expense", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    class Meta:
        ordering = ["-created_at"]
        db_table = "notifications"
