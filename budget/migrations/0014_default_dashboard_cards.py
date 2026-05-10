from django.db import migrations


def create_default_cards(apps, schema_editor):
    from budget.fixtures import DEFAULT_DASHBOARD_CARDS

    DashboardCard = apps.get_model('budget', 'DashboardCard')
    FeUser = apps.get_model('feusers', 'FeUser')

    for feuser in FeUser.objects.all():
        if not DashboardCard.objects.filter(owning_feuser=feuser).exists():
            DashboardCard.objects.bulk_create([
                DashboardCard(owning_feuser=feuser, yaml_config=entry['yaml'])
                for entry in DEFAULT_DASHBOARD_CARDS
            ])


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0013_remove_dashboardcard_redundant_cols'),
        ('feusers', '0017_feuser_last_login_last_seen'),
    ]

    operations = [
        migrations.RunPython(create_default_cards, migrations.RunPython.noop),
    ]
