from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0013_feuser_totp_recovery_hash_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="feuser",
            name="unspent_allowance_action",
            field=models.CharField(
                max_length=20,
                default="do_nothing",
                choices=[
                    ("do_nothing", "be dropped"),
                    ("deposit_savings", "be deposited as savings"),
                    ("carry_over", "carry over to next month"),
                ],
            ),
        ),
        migrations.AddField(
            model_name="feuser",
            name="allowance_transition_month",
            field=models.CharField(max_length=10, blank=True),
        ),
    ]
