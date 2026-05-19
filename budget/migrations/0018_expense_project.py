from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("budget", "0017_expense_is_buddies_settlement"),
        ("buddies", "0009_buddygroup_to_project"),
    ]

    operations = [
        migrations.RenameField(
            model_name="expense",
            old_name="buddy_group",
            new_name="project",
        ),
    ]
