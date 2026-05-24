from django.db import migrations


def delete_empty_dashboards(apps, schema_editor):
    Dashboard = apps.get_model('budget', 'Dashboard')
    Dashboard.objects.filter(title='Dashboard', cards__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0025_dashboard_multi_support'),
    ]

    operations = [
        migrations.RunPython(delete_empty_dashboards, migrations.RunPython.noop),
    ]
