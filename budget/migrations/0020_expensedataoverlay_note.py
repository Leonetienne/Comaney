from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("budget", "0019_expense_data_overlay"),
    ]

    operations = [
        migrations.AddField(
            model_name="expensedataoverlay",
            name="note",
            field=models.TextField(blank=True, default="", max_length=1024),
        ),
    ]
