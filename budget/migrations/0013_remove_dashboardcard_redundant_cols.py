from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0012_dashboardcard'),
    ]

    operations = [
        migrations.RemoveField(model_name='dashboardcard', name='position'),
        migrations.RemoveField(model_name='dashboardcard', name='width'),
        migrations.RemoveField(model_name='dashboardcard', name='height'),
    ]
