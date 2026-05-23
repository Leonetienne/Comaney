import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("budget", "0023_category_last_mod_dashboardcard_last_mod_and_more"),
        ("buddies", "0012_buddyinvite_last_mod_buddylink_last_mod_and_more"),
        ("feusers", "0025_feuser_last_mod"),
    ]

    operations = [
        migrations.AddField(
            model_name="scheduledexpense",
            name="assign_buddy_mode",
            field=models.CharField(blank=True, default="", max_length=10),
        ),
        migrations.AddField(
            model_name="scheduledexpense",
            name="assign_upfront_type",
            field=models.CharField(blank=True, default="me", max_length=10),
        ),
        migrations.AddField(
            model_name="scheduledexpense",
            name="assign_upfront_feuser",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="scheduled_assign_upfront",
                to="feusers.feuser",
            ),
        ),
        migrations.AddField(
            model_name="scheduledexpense",
            name="assign_upfront_dummy",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="scheduled_assign_upfront_dummy",
                to="buddies.dummyuser",
            ),
        ),
        migrations.AddField(
            model_name="scheduledexpense",
            name="assign_project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="scheduled_expenses",
                to="buddies.project",
            ),
        ),
        migrations.AddField(
            model_name="scheduledexpense",
            name="assign_spendings_json",
            field=models.TextField(blank=True, default="[]"),
        ),
    ]
