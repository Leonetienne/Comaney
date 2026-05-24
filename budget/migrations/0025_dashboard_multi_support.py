from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def backfill_dashboards(apps, schema_editor):
    FeUser = apps.get_model('feusers', 'FeUser')
    Dashboard = apps.get_model('budget', 'Dashboard')
    DashboardCard = apps.get_model('budget', 'DashboardCard')

    # For every user that has cards but no dashboard yet, create one dashboard
    # and assign all their cards to it.
    card_user_ids = (
        DashboardCard.objects.filter(dashboard__isnull=True)
        .values_list('owning_feuser_id', flat=True)
        .distinct()
    )
    for user_id in card_user_ids:
        dashboard = Dashboard.objects.create(
            owning_feuser_id=user_id,
            title='Dashboard',
            sorting=0,
        )
        DashboardCard.objects.filter(
            owning_feuser_id=user_id,
            dashboard__isnull=True,
        ).update(dashboard=dashboard)


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0024_scheduledexpense_assignment_fields'),
        ('feusers', '0001_initial'),
    ]

    operations = [
        # 1. Create budget_dashboard table
        migrations.CreateModel(
            name='Dashboard',
            fields=[
                ('uid', models.BigAutoField(primary_key=True, serialize=False)),
                ('owning_feuser', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='+',
                    to='feusers.feuser',
                )),
                ('title', models.CharField(max_length=128)),
                ('sorting', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('last_mod', models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                'ordering': ['sorting', 'uid'],
            },
        ),
        # 2. Add nullable dashboard FK to DashboardCard
        migrations.AddField(
            model_name='dashboardcard',
            name='dashboard',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='cards',
                to='budget.dashboard',
            ),
        ),
        # 3. Back-fill: create one Dashboard per user and assign existing cards
        migrations.RunPython(backfill_dashboards, migrations.RunPython.noop),
        # 4. Make the FK non-nullable
        migrations.AlterField(
            model_name='dashboardcard',
            name='dashboard',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='cards',
                to='budget.dashboard',
            ),
        ),
    ]
