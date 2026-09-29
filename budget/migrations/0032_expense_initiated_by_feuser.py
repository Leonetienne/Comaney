import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0031_sankeygraph'),
        ('feusers', '0039_yubikeyfactor'),
    ]

    operations = [
        migrations.AddField(
            model_name='expense',
            name='initiated_by_feuser',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='initiated_expenses', to='feusers.feuser'),
        ),
    ]
