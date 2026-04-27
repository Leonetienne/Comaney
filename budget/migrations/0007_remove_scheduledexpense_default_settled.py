from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("budget", "0006_auto_settle_on_due_date"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="scheduledexpense",
            name="default_settled",
        ),
    ]
