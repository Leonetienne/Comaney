from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0011_field_length_limits'),
        ('feusers', '0017_feuser_last_login_last_seen'),
    ]

    operations = [
        migrations.CreateModel(
            name='DashboardCard',
            fields=[
                ('uid', models.BigAutoField(primary_key=True, serialize=False)),
                ('owning_feuser', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='+',
                    to='feusers.feuser',
                )),
                ('yaml_config', models.TextField()),
                ('position', models.PositiveIntegerField(default=0)),
                ('width', models.PositiveIntegerField(default=2)),
                ('height', models.PositiveIntegerField(default=2)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['position', 'created_at'],
            },
        ),
    ]
