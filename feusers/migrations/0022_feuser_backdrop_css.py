from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feusers", "0021_feuser_backdrop_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="feuser",
            name="backdrop_css",
            field=models.TextField(blank=True, max_length=2000),
        ),
        migrations.AddField(
            model_name="feuser",
            name="backdrop_css_mobile",
            field=models.TextField(blank=True, max_length=2000),
        ),
    ]
